"""Ayudas de las pruebas del CRM. `_clean_tables` (conftest) vacía TODAS las tablas antes de cada prueba, también `crm_counters`: aquí se vuelven a sembrar como los deja la migración 0130."""
from sqlalchemy import text


def seed_counters(db, *, ready=True, account=0, event=0):
    db.execute(text("DELETE FROM crm_counters"))
    db.execute(text("INSERT INTO crm_counters (name, value, ready) VALUES ('account', :a, :r), ('event', :e, :r)"), {"a": account, "e": event, "r": ready})
    db.commit()
