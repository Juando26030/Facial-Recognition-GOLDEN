"""Fase 5 (A): estado «Facturado» (regla client_delivery, solo comercial o administrador, quién y cuándo) y base de datos final del evento (subir/reemplazar, aviso por correo a la comercial)."""
import io
import json
import pathlib
import zipfile

import pytest

from app import event_rules, final_db, jobs
from app.models import AuditAction, Event, EventState, Job
from app.storage import get_storage
from app.timeutil import utcnow
from tests.conftest import login

SRC = pathlib.Path(__file__).resolve().parent.parent
BILLED_RULES = {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": False, "touch_registration": False,
                "areas": True, "inventory_control": True, "certificates": True, "client_delivery": True}


def _state(db, name, base, position=None, **rules):
    s = EventState(name=name, base_status=base, position=db.query(EventState).count() if position is None else position, is_active=True, rules_json=json.dumps(rules))
    db.add(s)
    db.commit()
    return s


def _states(db):
    """Los estados de siempre + Facturado (como los deja la migración 0105)."""
    return (_state(db, "Creado", "creado"), _state(db, "En proceso", "en_proceso"), _state(db, "Finalizado", "finalizado"), _state(db, "Facturado", "finalizado", **BILLED_RULES))


def _xlsx(extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/extra.bin", extra)
    return buf.getvalue()


CSV = "nombre,cargo\nAna,Gerente\n".encode()


def _audit(db, action):
    db.expire_all()
    return db.query(AuditAction).filter(AuditAction.action == action).all()


# ------------------------------------------------------------------ regla y estado sembrado
def test_client_delivery_is_off_by_default_and_on_only_in_facturado(db, factory):
    creado, proceso, final, facturado = _states(db)
    for status, state in (("creado", creado), ("en_proceso", proceso), ("finalizado", final)):
        ev = factory.event(status, state_id=state.id)
        assert event_rules.effective_rules(ev)["client_delivery"] is False and not event_rules.allowed(ev, "client_delivery")
    ev = factory.event("finalizado", state_id=facturado.id)
    assert event_rules.allowed(ev, "client_delivery") is True
    assert ev.status == "finalizado"          # el estado base sigue mandando para el resto del sistema
    assert "client_delivery" in event_rules.RULES and all("client_delivery" in d for d in event_rules.DEFAULTS_BY_BASE.values())


def test_facturado_is_a_billing_state_and_the_others_are_not(db):
    _, _, final, facturado = _states(db)
    assert event_rules.is_billing_state(facturado) and not event_rules.is_billing_state(final) and not event_rules.is_billing_state(None)


def test_default_state_never_picks_facturado_even_if_it_sorts_first(db):
    facturado = _state(db, "Facturado", "finalizado", position=0, **BILLED_RULES)
    final = _state(db, "Finalizado", "finalizado", position=5)
    assert event_rules.default_state(db, "finalizado").id == final.id != facturado.id


def test_migration_seeds_facturado_after_finalizado_with_the_rule():
    src = (SRC / "alembic" / "versions" / "0105_event_billed.py").read_text(encoding="utf-8")
    assert 'revision = "0105_event_billed"' in src and len("0105_event_billed") <= 32 and 'down_revision = "0104_pledge_health_flags"' in src
    assert '"Facturado"' in src and '"base_status": "finalizado"' in src and '"client_delivery": True' in src
    for col in ("billed_at", "billed_by_id", "final_db_key", "final_db_name", "final_db_uploaded_at", "final_db_uploaded_by_id"):
        assert col in src
    assert 'ondelete="SET NULL"' in src


def test_states_listing_flags_billing_and_who_can_set_it(client, factory, db):
    _states(db)
    factory.staff("comercial", "com")
    factory.staff("coordinador", "coord")
    for user, expected in (("com", True), ("coord", False)):
        login(client, user)
        body = client.get("/api/event-states").json()
        assert body["can_set_billed"] is expected
        assert {s["name"]: s["billing"] for s in body["states"]}["Facturado"] is True and {s["name"]: s["billing"] for s in body["states"]}["Finalizado"] is False
        assert "client_delivery" in {r["key"] for r in body["rules"]}


# ------------------------------------------------------------------ quién puede ponerlo
def _setup(factory, db, who):
    _, _, final, facturado = _states(db)
    com = factory.staff("comercial", "com", email="com@example.com", full_name="Carla Comercial")
    coord = factory.staff("coordinador", "coord")
    dual = factory.staff("coordinador", "dual", secondary_role="comercial")
    factory.staff("admin", "root")
    ev = factory.event("finalizado", coordinator=dual if who == "dual" else coord, commercial=com, state_id=final.id, final_db_key="acme/final_database/x/base_final.xlsx", final_db_name="Base final.xlsx")
    return ev, facturado, final


@pytest.mark.parametrize("who,allowed", [("com", True), ("root", True), ("dual", True), ("coord", False)])
def test_only_a_comercial_or_admin_can_mark_facturado(client, factory, db, who, allowed):
    ev, facturado, final = _setup(factory, db, who)
    ev_id = ev.id
    login(client, who)
    r = client.patch(f"/api/events/{ev_id}", json={"state_id": facturado.id})
    assert (r.status_code == 200) is allowed, r.text
    db.expire_all()
    ev = db.get(Event, ev_id)
    if allowed:
        assert ev.state_id == facturado.id and ev.status == "finalizado"
        assert ev.billed_at is not None and ev.billed_by.username == who
        assert [a.actor_id for a in _audit(db, "billed")] == [ev.billed_by_id]
        body = client.get(f"/api/events/{ev_id}").json()
        assert body["billed"] is True and body["billed_by_name"] and body["billed_at"] and body["state_name"] == "Facturado"
    else:
        assert r.status_code == 403 and "comercial" in r.json()["detail"]
        assert ev.state_id == final.id and ev.billed_at is None and ev.billed_by_id is None and not _audit(db, "billed")


def test_a_coordinator_cannot_mark_facturado_with_the_plain_status_either(client, factory, db):
    ev, facturado, final = _setup(factory, db, "coord")
    login(client, "coord")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "finalizado"}).status_code == 200          # no cambia nada: sigue en Finalizado
    db.expire_all()
    assert db.get(Event, ev.id).state_id == final.id


def test_only_a_finalized_event_can_be_billed(client, factory, db):
    _, _, _, facturado = _states(db)
    com = factory.staff("comercial", "com")
    ev = factory.event("en_proceso", commercial=com)
    login(client, "com")
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id})
    assert r.status_code == 400 and "Finalizado" in r.json()["detail"]


def test_facturado_requires_the_final_database_attached(client, factory, db):
    ev, facturado, final = _setup(factory, db, "coord")
    ev.final_db_key = ev.final_db_name = None
    db.commit()
    login(client, "com")
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id})
    assert r.status_code == 400 and "base de datos final" in r.json()["detail"]
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.state_id == final.id and got.billed_at is None and not _audit(db, "billed")
    got.final_db_key = "acme/final_database/x/base_final.xlsx"
    db.commit()
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id}).status_code == 200


def test_coordinator_can_still_edit_a_billed_event_without_touching_its_state_but_cannot_leave_it(client, factory, db):
    ev, facturado, final = _setup(factory, db, "coord")
    login(client, "com")
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id}).status_code == 200
    login(client, "coord")
    assert client.patch(f"/api/events/{ev.id}", json={"notes": "ajuste"}).status_code == 200
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": final.id}).status_code == 403
    assert client.patch(f"/api/events/{ev.id}", json={"status": "creado"}).status_code in (400, 403)
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.state_id == facturado.id and got.billed_at is not None and got.notes == "ajuste"


def test_leaving_facturado_clears_billed_fields_and_keeps_the_history(client, factory, db):
    ev, facturado, final = _setup(factory, db, "coord")
    login(client, "com")
    client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id})
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": final.id})
    assert r.status_code == 200 and r.json()["billed"] is False
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.billed_at is None and got.billed_by_id is None and got.state_id == final.id
    assert len(_audit(db, "billed")) == 1 and len(_audit(db, "unbilled")) == 1          # quién y cuándo siguen en el historial


def test_billing_does_not_change_the_biometric_retention_clock(client, factory, db):
    ev, facturado, _ = _setup(factory, db, "coord")
    ev.finalized_at = stamped = utcnow()
    db.commit()
    login(client, "com")
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id}).status_code == 200
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.status == "finalizado" and got.finalized_at == stamped


def test_the_edit_modal_and_events_page_have_the_billing_ui():
    modal = (SRC / "templates" / "_event_edit_modal.html").read_text(encoding="utf-8")
    assert 'id="eeBilledInfo"' in modal and "Facturado" in modal and "can_set_billed" in modal and 'id="eeFinalDbUpload"' in modal and "final-database" in modal
    assert "onclick=" not in modal and "alert(" not in modal
    assert "editar" in (SRC / "templates" / "eventos.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ base de datos final
@pytest.fixture()
def final_setup(factory, db, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")
    com = factory.staff("comercial", "com", email="com@example.com", full_name="Carla Comercial")
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("finalizado", coordinator=coord, commercial=com)
    return ev, com, coord


def _upload(client, ev_id, name, content, **kw):
    return client.post(f"/api/events/{ev_id}/final-database", files={"file": (name, content, "application/octet-stream")}, **kw)


def test_coordinator_uploads_the_final_database_and_the_commercial_gets_an_email(client, final_setup, db, outbox):
    ev, com, _ = final_setup
    login(client, "coord")
    r = _upload(client, ev.id, "Base final.xlsx", _xlsx())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replaced"] is False and body["notice_queued"] is True and body["final_db_name"] == "Base final.xlsx"
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.final_db_key == f"acme/final_database/{ev.id}/base_final.xlsx" and got.final_db_uploaded_by_id and got.final_db_uploaded_at is not None
    assert get_storage().get(got.final_db_key) == _xlsx()
    assert [a.entity_id for a in _audit(db, "final_db_upload")] == [str(ev.id)]
    assert len(outbox) == 1
    mail = outbox[0]
    assert mail["to"] == "com@example.com"
    assert f"Ya se subió la base de datos final del evento {ev.name}. Revisa si ya se puede facturar el evento." in mail["body"]
    assert f"https://app.example.com/eventos?editar={ev.id}" in mail["body"] and f"https://app.example.com/eventos?editar={ev.id}" in mail["html"]
    assert "\n" not in mail["subject"]
    ser = client.get(f"/api/events/{ev.id}").json()
    assert ser["final_db_uploaded"] is True and ser["final_db_uploaded_by_name"]


def test_the_queued_job_carries_no_personal_data(client, final_setup, db, monkeypatch):
    ev, *_ = final_setup
    monkeypatch.setattr(jobs, "kick", lambda *a, **k: None)          # que el trabajo se quede en cola para poder mirarlo
    login(client, "coord")
    assert _upload(client, ev.id, "Ana Pérez 1001.csv", CSV).status_code == 200
    job = db.query(Job).filter(Job.kind == final_db.KIND).one()
    assert json.loads(job.payload_json) == {"event_id": ev.id}
    assert "Ana" not in job.payload_json and "1001" not in job.payload_json
    audit = _audit(db, "final_db_upload")[0]
    assert "Ana" not in (audit.detail or "")          # ni el nombre del archivo ni nada personal en la auditoría


def test_replacing_the_final_database_overwrites_audits_and_notifies_again(client, final_setup, db, outbox):
    ev, *_ = final_setup
    login(client, "coord")
    assert _upload(client, ev.id, "uno.xlsx", _xlsx()).status_code == 200
    first_key = db.get(Event, ev.id).final_db_key
    r = _upload(client, ev.id, "dos.csv", CSV)
    assert r.status_code == 200 and r.json()["replaced"] is True
    db.expire_all()
    got = db.get(Event, ev.id)
    assert got.final_db_key.endswith("base_final.csv") and got.final_db_name == "dos.csv" and get_storage().get(got.final_db_key) == CSV
    assert not get_storage().exists(first_key)          # la anterior (otro formato) se borra
    assert len(_audit(db, "final_db_upload")) == 1 and len(_audit(db, "final_db_replace")) == 1
    assert len(outbox) == 2


def test_the_commercial_and_the_admin_can_upload_too(client, final_setup, factory):
    ev, *_ = final_setup
    factory.staff("admin", "root")
    for user in ("com", "root"):
        login(client, user)
        assert _upload(client, ev.id, "base.csv", CSV).status_code == 200, user


def test_no_commercial_or_no_email_uploads_fine_without_a_notice(client, factory, db, outbox):
    coord = factory.staff("coordinador", "coord")
    login(client, "coord")
    sin = factory.event("finalizado", coordinator=coord)
    r = _upload(client, sin.id, "base.csv", CSV)
    assert r.status_code == 200 and r.json()["notice_queued"] is False and "comercial" in r.json()["notice"]
    com = factory.staff("comercial", "com2")          # sin correo
    sin_correo = factory.event("finalizado", coordinator=coord, commercial=com)
    r = _upload(client, sin_correo.id, "base.csv", CSV)
    assert r.status_code == 200 and r.json()["notice_queued"] is False and "correo" in r.json()["notice"]
    assert outbox == [] and db.query(Job).filter(Job.kind == final_db.KIND).count() == 0


@pytest.mark.parametrize("name,content,fragment", [
    ("base.pdf", b"%PDF-1.4 x", "Excel"), ("base.xlsx", b"esto no es un zip", "Excel"), ("base.xlsx", b"", "vacío"), ("base.csv", b"a,b\n\x00\x01", "Excel"),
    ("base.csv", b"%PDF-1.4 x", "Excel"), ("base.exe", b"MZ", "Excel"),
])
def test_invalid_files_are_rejected_in_spanish(client, final_setup, db, outbox, name, content, fragment):
    ev, *_ = final_setup
    login(client, "coord")
    r = _upload(client, ev.id, name, content)
    assert r.status_code == 400 and fragment in r.json()["detail"]
    db.expire_all()
    assert db.get(Event, ev.id).final_db_key is None and outbox == []


def test_oversize_file_is_rejected(client, final_setup, monkeypatch):
    ev, *_ = final_setup
    monkeypatch.setattr(final_db, "MAX_BYTES", 10)
    login(client, "coord")
    r = _upload(client, ev.id, "base.csv", CSV)
    assert r.status_code == 400 and "pesa más" in r.json()["detail"]


def test_a_zip_without_spreadsheet_parts_is_not_an_xlsx(client, final_setup):
    ev, *_ = final_setup
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hola.txt", "x")
    login(client, "coord")
    assert _upload(client, ev.id, "base.xlsx", buf.getvalue()).status_code == 400


def test_upload_without_a_file_is_a_400(client, final_setup):
    ev, *_ = final_setup
    login(client, "coord")
    assert client.post(f"/api/events/{ev.id}/final-database").status_code == 400


def test_digitador_and_cliente_cannot_upload_or_download(client, final_setup, factory, db):
    ev, *_ = final_setup
    dig, cli = factory.staff("digitador", "dig"), factory.staff("cliente", "cli")
    factory.authorize(ev, dig)
    factory.authorize(ev, cli)
    ev.status = "en_proceso"
    db.commit()
    for user in ("dig", "cli"):
        login(client, user)
        assert _upload(client, ev.id, "base.csv", CSV).status_code == 403, user
        assert client.get(f"/api/events/{ev.id}/final-database").status_code == 403, user
    db.expire_all()
    assert db.get(Event, ev.id).final_db_key is None


def test_anonymous_cannot_upload(client, final_setup):
    ev, *_ = final_setup
    assert _upload(client, ev.id, "base.csv", CSV).status_code in (401, 302, 303, 403)


def test_a_coordinator_of_another_event_cannot_upload_when_scope_is_enforced(client, final_setup, factory, monkeypatch):
    ev, *_ = final_setup
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    factory.staff("coordinador", "otra")
    login(client, "otra")
    assert _upload(client, ev.id, "base.csv", CSV).status_code == 404
    assert client.get(f"/api/events/{ev.id}/final-database").status_code == 404


def test_archived_event_and_archived_base_block_the_upload(client, final_setup, db):
    ev, *_ = final_setup
    login(client, "coord")
    ev.data_archived_at = utcnow()
    db.commit()
    assert _upload(client, ev.id, "base.csv", CSV).status_code == 403
    ev.data_archived_at, ev.archived_at = None, utcnow()
    db.commit()
    assert _upload(client, ev.id, "base.csv", CSV).status_code == 400


def test_download_returns_the_file_and_404_when_there_is_none(client, final_setup):
    ev, *_ = final_setup
    login(client, "coord")
    assert client.get(f"/api/events/{ev.id}/final-database").status_code == 404
    _upload(client, ev.id, "base.csv", CSV)
    r = client.get(f"/api/events/{ev.id}/final-database")
    assert r.status_code == 200 and r.content == CSV and ev.event_code in r.headers["content-disposition"]


def test_direct_upload_token_path_for_big_files(client, final_setup, db):
    ev, *_ = final_setup
    login(client, "coord")
    sig = client.post("/api/uploads", json={"purpose": "final_database", "event_id": ev.id, "filename": "grande.csv", "size": len(CSV), "content_type": "text/csv"})
    assert sig.status_code == 200, sig.text
    sig = sig.json()
    assert client.put(sig["url"], content=CSV, headers=sig["headers"]).status_code in (200, 201, 204)
    r = client.post(f"/api/events/{ev.id}/final-database", data={"upload_token": sig["token"]})
    assert r.status_code == 200 and r.json()["final_db_name"] == "grande.csv"
    db.expire_all()
    assert get_storage().get(db.get(Event, ev.id).final_db_key) == CSV
    wrong = client.post("/api/uploads", json={"purpose": "final_database", "event_id": ev.id, "filename": "x.pdf", "size": 3, "content_type": "application/pdf"})
    assert wrong.status_code == 400          # el propósito solo admite xlsx y csv


def test_the_job_is_declared_everywhere_a_new_job_kind_must_be():
    assert final_db.KIND in jobs.GENERAL_KINDS and jobs.HANDLER_MODULES[final_db.KIND] == "app.final_db"
    assert '@jobs.handler("final_db_notice")' in (SRC / "app" / "final_db.py").read_text(encoding="utf-8")


def test_handler_does_nothing_when_the_base_was_removed_or_the_commercial_has_no_email(final_setup, db, outbox):
    ev, com, _ = final_setup
    final_db.run_notice({"event_id": ev.id})          # sin base subida: no avisa
    assert outbox == []
    ev.final_db_key = "acme/final_database/x/base_final.csv"
    com.email = None
    db.commit()
    final_db.run_notice({"event_id": ev.id})
    assert outbox == []


def test_email_text_escapes_the_event_name():
    mail = final_db.render("<b>Feria</b>", "Ana", "https://app.example.com/eventos?editar=1")
    assert "<b>Feria</b>" not in mail["html"] and "&lt;b&gt;Feria&lt;/b&gt;" in mail["html"] and "\n" not in mail["subject"]
    assert "Ya se subió la base de datos final del evento <b>Feria</b>. Revisa si ya se puede facturar el evento." in mail["text"]


def test_billing_sends_the_survey_by_itself_to_the_primary_contact(client, factory, db):
    """16-nov-2026: al pasar a «Facturado» la encuesta se encola sola para el contacto PRINCIPAL del evento (y sin contacto con correo no se envía y se avisa, sin deshacer el cambio)."""
    from app import event_contacts
    ev, facturado, _ = _setup(factory, db, "com")
    event_contacts.replace(db, ev, [{"name": "Ana Cliente", "phone": "300", "email": "ana@example.com", "is_primary": True}])
    db.commit()
    login(client, "com")
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id})
    assert r.status_code == 200, r.text
    sv = r.json()["survey_email"]
    assert sv["sent"] is True and sv["recipient"] == "ana@example.com"
    assert db.query(Job).filter(Job.kind == "delivery_mail").count() == 1


def test_billing_without_a_contact_email_still_bills_and_says_why(client, factory, db):
    ev, facturado, _ = _setup(factory, db, "com")
    login(client, "com")
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": facturado.id})
    assert r.status_code == 200 and r.json()["survey_email"]["sent"] is False and "contacto principal" in r.json()["survey_email"]["detail"]
    db.expire_all()
    assert db.get(Event, ev.id).billed_at is not None and db.query(Job).filter(Job.kind == "delivery_mail").count() == 0
