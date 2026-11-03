"""0C (E2/E3): la cola de trabajos no guarda cédulas en claro ni errores sin enmascarar. Solo DATOS, sin cambios de esquema.

  * `jobs.payload_json` de los trabajos TERMINADOS (`done`): se les quita `user_id` (la cédula) y `uref`; ya no hacen falta. Los pendientes o fallidos conservan su `user_id` en claro
    hasta que corren (el manejador entiende tanto `user_id` como la referencia sellada `uref` que ahora escribe el código) o hasta que se suprima a la persona.
  * `jobs.last_error`: los números largos (cédulas, teléfonos) y los correos se enmascaran con la misma regla de `app.obs.mask_pii`.

Compatible con Neon (pooler en modo transacción): solo UPDATE, sin SET de sesión. Idempotente. Bajarla no restaura lo enmascarado (es irreversible a propósito).

Revision ID: 0078_jobs_sin_cedulas
Revises: 0077_event_status_changes
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0078_jobs_sin_cedulas"
down_revision = "0077_event_status_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE jobs SET payload_json = ((payload_json::jsonb) - 'user_id' - 'uref')::text "
        "WHERE status = 'done' AND payload_json LIKE '{%' AND ((payload_json::jsonb)->>'user_id' IS NOT NULL OR (payload_json::jsonb)->>'uref' IS NOT NULL)"))
    bind.execute(sa.text(
        "UPDATE jobs SET last_error = regexp_replace(regexp_replace(last_error, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', '***@***', 'g'), '[0-9]{6,}', '***', 'g') "
        "WHERE last_error IS NOT NULL AND last_error ~ '([0-9]{6,}|@)'"))


def downgrade() -> None:
    pass         # lo enmascarado no se puede restaurar (a propósito)
