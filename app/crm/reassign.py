"""Pasa a un usuario (p. ej. la comercial) todo lo que vino de SuiteCRM: `python -m app.crm.reassign <usuario>`.
Solo toca filas con legacy_sugar_id (lo importado); lo creado a mano en GoldenWeb no se mueve. Imprime solo conteos."""
import sys

from sqlalchemy import update

from app.database import SessionLocal
from app.models import CrmAccount, CrmActivity, CrmOpportunity, CrmQuote, StaffUser


def reassign(db, username: str) -> dict:
    user = db.query(StaffUser).filter(StaffUser.username == username).first()
    if user is None:
        raise SystemExit("No existe ese usuario.")
    out = {}
    for name, model in (("accounts", CrmAccount), ("opportunities", CrmOpportunity), ("activities", CrmActivity), ("quotes", CrmQuote)):
        res = db.execute(update(model).where(model.legacy_sugar_id.isnot(None), model.owner_staff_id.is_distinct_from(user.id)).values(owner_staff_id=user.id))
        out[name] = res.rowcount
    db.commit()
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m app.crm.reassign <usuario>")
    db = SessionLocal()
    try:
        print("Reasignadas:", reassign(db, sys.argv[1]))
    finally:
        db.close()
