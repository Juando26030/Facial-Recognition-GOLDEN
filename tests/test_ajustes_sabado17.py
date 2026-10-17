"""Ajustes del sábado 17-oct: (A) la pantalla de carga avisa ANTES con la misma regla que el servidor, (C) una sola fuente de URL pública, (E) un solo texto para «reemplazar fechas»."""
import logging

import pytest

from app import acceptlink, event_rules, publicurl
from app.models import EventAttendee
from app.routers import api
from tests.conftest import login


def _coord(client, factory, status, **kw):
    factory.staff("coordinador", "coord1")
    ev = factory.event(status, **kw)
    login(client, "coord1")
    return ev


def _csv_post(client, ev):
    return client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", b"id,nombres,apellidos\n1001,Ana,Mora\n", "text/csv")})


# ------------------------------------------------------------------------------------------------------------------------------------ (A)
@pytest.mark.parametrize("status, uploaded, blocked", [("finalizado", False, True), ("finalizado", True, True), ("en_proceso", True, True), ("en_proceso", False, False), ("creado", False, False), ("creado", True, False)])
def test_one_rule_decides_screen_and_server(client, factory, status, uploaded, blocked):
    ev = _coord(client, factory, status, roster_uploaded=uploaded)
    reason = event_rules.roster_block_reason(ev)
    assert bool(reason) is blocked
    page = client.get(f"/kiosk/{ev.id}/roster").text
    post = _csv_post(client, ev)
    if blocked:
        assert 'id="rosterBlocked"' in page and ("EN PROCESO" in page or "FINALIZADO" in page)
        assert 'id="rosterSubmit"' in page and 'disabled aria-disabled="true"' in page and "<fieldset disabled" in page
        assert "const ROSTER_BLOCKED = true" in page and post.status_code == 400 and post.json()["detail"] == reason      # el servidor dice lo mismo que la pantalla
        assert "Sí, cargar de todas formas" not in page
    else:
        assert 'id="rosterBlocked"' not in page and "const ROSTER_BLOCKED = false" in page and 'disabled aria-disabled="true"' not in page
        assert post.status_code == 200


def test_blocked_messages_say_what_happens_and_what_to_do():
    assert "FINALIZADO" in event_rules.ROSTER_BLOCKED_FINALIZED and "«Creado»" in event_rules.ROSTER_BLOCKED_FINALIZED
    assert "ya tiene una base cargada" in event_rules.ROSTER_BLOCKED_IN_PROGRESS and "«Creado»" in event_rules.ROSTER_BLOCKED_IN_PROGRESS and "evento nuevo" in event_rules.ROSTER_BLOCKED_IN_PROGRESS


# ------------------------------------------------------------------------------------------------------------------------------------ (C)
def test_with_the_variable_set_it_is_always_used_even_in_production(monkeypatch):
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.golden-eventos.com/")
    assert publicurl.base("https://golden-web-298291650070.us-east4.run.app/") == "https://app.golden-eventos.com"


def test_in_production_without_the_variable_it_warns_and_never_falls_back_to_cloud_run(monkeypatch, caplog):
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(publicurl, "_last_warn", {"missing": 0.0, "run_app": 0.0})
    with caplog.at_level(logging.WARNING, logger="golden.publicurl"):
        assert publicurl.base("https://golden-web-298291650070.us-east4.run.app/") == ""
    assert any("Falta PUBLIC_BASE_URL en PRODUCCIÓN" in r.message for r in caplog.records)


def test_in_production_a_cloud_run_host_in_the_variable_is_warned(monkeypatch, caplog):
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://golden-web-298291650070.us-east4.run.app")
    monkeypatch.setattr(publicurl, "_last_warn", {"missing": 0.0, "run_app": 0.0})
    with caplog.at_level(logging.WARNING, logger="golden.publicurl"):
        publicurl.check_at_startup()
    assert any("host de Cloud Run" in r.message for r in caplog.records)


def test_outside_production_the_request_host_is_the_fallback(monkeypatch):
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert publicurl.base("http://testserver/") == "http://testserver"


def test_every_absolute_link_follows_the_one_variable(client, factory, db, monkeypatch):
    """Enlace personal, CSV de enlaces, política en el texto de consentimiento y QR del cartel: todos con PUBLIC_BASE_URL, aunque el panel se abra por otro host."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://golden-staging-298291650070.web.app")
    ev = _coord(client, factory, "en_proceso", facial_enabled=True, aceptar_enabled=True)
    u = factory.person(ev, "1001", "Ana", "Mora")
    u.email = "ana@example.com"
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").one()
    token = acceptlink.issue(db, att, True)
    db.commit()
    assert acceptlink.url(ev, token, "https://golden-web-staging-298291650070.us-east4.run.app").startswith("https://golden-staging-298291650070.web.app/aceptar/")
    csv = client.get(f"/api/events/{ev.id}/accept-links.csv", headers={"host": "golden-web-staging-298291650070.us-east4.run.app"}).text
    assert "https://golden-staging-298291650070.web.app/aceptar/" in csv and "run.app" not in csv
    text = client.get(f"/api/aceptar/{ev.event_code}/text").json()
    assert "golden-staging-298291650070.web.app/privacidad" in " ".join(text["body"]) and "run.app" not in " ".join(text["body"])
    page = client.get(f"/kiosk/{ev.id}/parametros", headers={"host": "golden-web-staging-298291650070.us-east4.run.app"}).text
    assert 'window.PUBLIC_BASE = "https://golden-staging-298291650070.web.app"' in page and "${window.PUBLIC_BASE || location.origin}/aceptar/" in page
    editor_src = open("templates/kiosk_formulario_editor.html", encoding="utf-8").read()
    assert editor_src.count("window.PUBLIC_BASE || location.origin") == 2 and "${location.origin}/f/" not in editor_src and "${location.origin}/webhooks" not in editor_src


def test_no_code_builds_a_link_straight_from_the_request_host():
    import pathlib
    offenders = []
    for path in pathlib.Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name != "publicurl.py" and 'os.getenv("PUBLIC_BASE_URL") or str(request.base_url)' in text:
            offenders.append(str(path))
    assert offenders == []


def test_the_deploy_workflow_passes_the_variable_through():
    wf = open(".github/workflows/cloudrun-deploy.yml", encoding="utf-8").read()
    assert "PUBLIC_BASE_URL: ${{ vars.PUBLIC_BASE_URL }}" in wf


# ------------------------------------------------------------------------------------------------------------------------------------ (E)
def test_the_replace_dates_text_is_one_constant_used_by_the_checkbox_and_the_summary(client, factory, db):
    label = api.OVERWRITE_BIRTH_LABEL
    assert label == "Reemplazar las fechas de nacimiento que ya están guardadas"
    ev = _coord(client, factory, "creado", facial_enabled=True)
    assert label in client.get(f"/kiosk/{ev.id}/roster").text
    csv1 = b"id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,26/03/2005\n"
    csv2 = b"id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,01/01/1980\n"
    client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", csv1, "text/csv")})
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", csv2, "text/csv")}).json()
    assert any(f"«{label}»" in e for e in r["errors"])
