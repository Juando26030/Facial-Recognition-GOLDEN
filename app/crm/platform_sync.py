"""Revisa (y, si se pide, completa) el enlace CRM ↔ plataforma de lo que ya existe: `python -m app.crm.platform_sync [--apply --as <usuario>]`.

Sin `--apply` solo cuenta (simulacro). Con `--apply`: crea la cuenta de los clientes con número consecutivo que no la tienen y la oportunidad ganada de los eventos que no tienen ninguna.
NO convierte en clientes las cuentas del CRM (solo las cuenta): eso lo decide Juan David. Imprime solo conteos, nunca nombres ni datos de personas."""
import argparse
import re

from sqlalchemy import exists

from app.crm import platform_link
from app.database import SessionLocal
from app.models import CrmAccount, CrmOpportunity, Event, StaffUser, Tenant

_NUMERIC = re.compile(r"^[0-9]{1,7}$")


def report(db) -> dict:
    tenants = db.query(Tenant).filter(Tenant.archived_at.is_(None)).all()
    has_account = {tid for (tid,) in db.query(CrmAccount.tenant_id).filter(CrmAccount.tenant_id.isnot(None)).all()}
    missing = [t for t in tenants if t.id not in has_account]
    events = db.query(Event).filter(~exists().where(CrmOpportunity.event_id == Event.id)).all()
    won_no_client = (db.query(CrmAccount.id).filter(CrmAccount.tenant_id.is_(None), exists().where((CrmOpportunity.account_id == CrmAccount.id) & (CrmOpportunity.outcome == "won"))).count())
    return {"clientes_sin_cuenta_con_numero": sum(1 for t in missing if _NUMERIC.match(t.client_code or "")),
            "clientes_sin_cuenta_codigo_antiguo": sum(1 for t in missing if not _NUMERIC.match(t.client_code or "")),
            "eventos_sin_oportunidad": len(events),
            "cuentas_con_oportunidad_ganada_sin_ser_cliente": won_no_client}


def apply(db, staff: StaffUser) -> dict:
    done = {"cuentas_creadas": 0, "oportunidades_creadas": 0, "eventos_sin_enlazar": 0}
    for t in db.query(Tenant).filter(Tenant.archived_at.is_(None)).all():
        if _NUMERIC.match(t.client_code or "") and platform_link.account_for_tenant(db, t.id) is None:
            if platform_link.ensure_account(db, staff, t) is not None:
                done["cuentas_creadas"] += 1
    db.commit()
    for e in db.query(Event).filter(~exists().where(CrmOpportunity.event_id == Event.id)).all():
        if platform_link.ensure_opportunity(db, staff, e) is not None:
            done["oportunidades_creadas"] += 1
        else:
            done["eventos_sin_enlazar"] += 1
        db.commit()
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--as", dest="username", default="")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        print("Estado:", report(db))
        if args.apply:
            staff = db.query(StaffUser).filter(StaffUser.username == args.username).first()
            if staff is None:
                raise SystemExit("Con --apply hay que decir con qué usuario: --as <usuario>.")
            print("Hecho:", apply(db, staff))
            print("Estado ahora:", report(db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
