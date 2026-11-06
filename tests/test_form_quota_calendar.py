"""Calendario propio de cada cupo en el envío público y en el estado de cupos."""
import json
from datetime import datetime, timedelta

from app import formsvc
from tests.test_form_align_to_base import _form


def _set_schedule(db, f, rule_label, schedule):
    from app.models import WebForm
    form = db.query(WebForm).get(f["id"])
    st = json.loads(form.settings_json)
    for r in st["quotas"]["rules"]:
        if r["label"] == rule_label:
            r["schedule"] = schedule
    form.settings_json = json.dumps(st)
    db.commit()
    formsvc.invalidate_public_cache()


def test_quota_status_and_public_closed_by_calendar(client, factory, db):
    ev, f = _form(client, factory, db)
    now = formsvc.now_local()
    fmt = "%Y-%m-%dT%H:%M"
    _set_schedule(db, f, "Cali", [{"status": "activo", "from": (now - timedelta(hours=1)).strftime(fmt), "to": (now + timedelta(hours=1)).strftime(fmt)}])
    _set_schedule(db, f, "Bogotá", [{"status": "activo", "from": (now + timedelta(days=1)).strftime(fmt), "to": (now + timedelta(days=2)).strftime(fmt)}])
    st = {s["id"]: s for s in client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["quota_status"]}
    names = {r["label"]: r["id"] for r in client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["settings"]["quotas"]["rules"]}
    assert st[names["Cali"]]["schedule"]["state"] == "abierto" and st[names["Cali"]]["left"] == 10
    assert st[names["Bogotá"]]["schedule"]["state"] == "cerrado" and st[names["Bogotá"]]["left"] == 0 and st[names["Bogotá"]]["schedule"]["opens"]
