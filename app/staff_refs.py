"""Borrar una cuenta del personal sin romper llaves foráneas (D3, 6-nov-2026).

Antes, «Borrar permanente» (`DELETE /api/staff/{id}`) y el borrado en bloque de digitadores (`POST /events/{id}/staff-users/purge-temporary`) soltaban a mano
unas pocas referencias (eventos, ingresos, autorizaciones) y fallaban con IntegrityError (500) en cuanto la cuenta había impreso una escarapela
(`print_logs.printed_by_staff_id`), movido a alguien de área, entregado inventario, lanzado una carga (`bulk_jobs.staff_user_id`) o creado un formulario
(`web_forms.created_by_id`). Aquí la lista NO se escribe a mano: se lee del catálogo de Postgres (`pg_constraint`), así una tabla nueva que apunte a
`staff_users` queda cubierta sola.

Regla por cada llave foránea de una sola columna hacia `staff_users.id`:
  * ON DELETE CASCADE / SET NULL / SET DEFAULT: la base ya sabe qué hacer, no se toca.
  * columna que admite NULL: se pone en NULL (el dato de negocio se conserva; solo pierde «quién lo hizo»).
  * columna NOT NULL de una tabla desechable (enlaces de restablecer contraseña, autorizaciones por evento): se borran esas filas.
  * otra columna NOT NULL con filas de esta cuenta: NO se puede borrar sin perder datos → la cuenta se DESACTIVA (y se cierra su sesión).
Compatible con el pooler de Neon: solo consultas del catálogo, UPDATE/DELETE y SAVEPOINT (nada de SET de sesión ni locks de sesión)."""
import logging
import re

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import StaffUser

log = logging.getLogger("golden.staff_refs")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
DISPOSABLE = {("password_reset_tokens", "staff_user_id"), ("event_staff_authorizations", "staff_user_id")}
_FK_SQL = text("""
SELECT cl.relname, att.attname, att.attnotnull, con.confdeltype
FROM pg_constraint con
JOIN pg_class cl ON cl.oid = con.conrelid
JOIN pg_namespace ns ON ns.oid = cl.relnamespace
JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
WHERE con.contype = 'f' AND con.confrelid = 'staff_users'::regclass AND cardinality(con.conkey) = 1
ORDER BY cl.relname, att.attname
""")


def staff_fk_columns(db: Session) -> list:
    """[(tabla, columna, not_null, regla_on_delete)] de las llaves foráneas hacia staff_users (regla: 'a' sin acción, 'r' restrict, 'c' cascade, 'n' set null, 'd' default)."""
    return [(t, c, bool(nn), d if isinstance(d, str) else bytes(d).decode()) for t, c, nn, d in db.execute(_FK_SQL).all()]


def release(db: Session, staff_id: int) -> list:
    """Suelta lo que apunta a la cuenta `staff_id` (ver el encabezado). Devuelve [(tabla, columna)] NOT NULL que la siguen mencionando: si no está vacía,
    la cuenta no se puede borrar. No hace commit."""
    blocked = []
    for table, column, not_null, on_delete in staff_fk_columns(db):
        if on_delete in ("c", "n", "d"):
            continue
        if not (_IDENT.match(table) and _IDENT.match(column)):          # nombres del catálogo, pero igual nunca se interpola algo raro
            blocked.append((table, column))
            continue
        params = {"s": staff_id}
        try:
            with db.begin_nested():
                if (table, column) in DISPOSABLE:
                    db.execute(text(f'DELETE FROM "{table}" WHERE "{column}" = :s'), params)  # nosec B608 - tabla/columna del catálogo, validadas con _IDENT; el id va enlazado
                elif not_null:
                    if db.execute(text(f'SELECT 1 FROM "{table}" WHERE "{column}" = :s LIMIT 1'), params).first():  # nosec B608 - ídem
                        blocked.append((table, column))
                else:
                    db.execute(text(f'UPDATE "{table}" SET "{column}" = NULL WHERE "{column}" = :s'), params)  # nosec B608 - ídem
        except DBAPIError:              # p. ej. una tabla de solo inserción (trigger): esa referencia se queda y la cuenta se desactiva en vez de borrarse
            log.warning("no se pudo soltar la referencia %s.%s a una cuenta del personal", table, column)
            blocked.append((table, column))
    return blocked


def delete_or_deactivate(db: Session, target: StaffUser) -> str:
    """Borra la cuenta si se puede soltar todo lo que la menciona; si no, la desactiva y le cierra la sesión. Devuelve 'deleted' o 'deactivated'. No hace commit."""
    staff_id = target.id
    if release(db, staff_id):
        target.is_active = False
        target.session_token = None
        db.flush()
        return "deactivated"
    db.query(StaffUser).filter(StaffUser.id == staff_id).delete(synchronize_session=False)
    db.expunge(target)
    return "deleted"
