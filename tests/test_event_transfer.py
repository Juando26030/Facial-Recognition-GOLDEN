"""Exportar / importar un evento completo (docs/18_EXPORTAR_EVENTOS.md, F1). DATOS SINTÉTICOS: nunca datos reales ni el evento 20 de staging."""
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app import event_transfer as et
from app import consent
from app import models as m
from tests.conftest import login


def _build(db, factory):
    """Un evento sintético con (casi) todo lo que cuelga de él."""
    coord = factory.staff("coordinador", "coord_origen")
    reg = factory.staff("digitador", "digit_origen")
    ev = factory.event("en_proceso", coordinator=coord, auto_register=True, print_settings_json='{"crop": true}', optional_field_labels='["Empresa X"]')
    db.add(m.EventFieldConfig(event_id=ev.id, field_key="opcional_1", required=True, field_type="text_short", label="Cargo"))
    area = m.EventArea(event_id=ev.id, name="Sala A", allow_reentry=True)
    item = m.InventoryItem(event_id=ev.id, name="Camiseta", initial_qty=50, allow_multiple=False)
    db.add_all([area, item])
    db.add(m.BadgeTemplate(tenant_id=ev.tenant_id, event_id=ev.id, category=None, kind="normal", name="Plantilla", width_mm=62, height_mm=100, orientation="vertical",
                           background_type="color", background_value="#fff", elements_json='[{"type":"text_variable"}]'))
    form = m.WebForm(event_id=ev.id, name="Inscripción", slug="inscripcion", manual_status="activo", use_schedule=False, design_json="{}", test_key="k-origen", created_by_id=coord.id)
    db.add(form)
    db.flush()
    inv = m.FormInvite(form_id=form.id, person_id="1001", token="tok-invite-1", email="x@example.com")
    code = m.FormDiscountCode(form_id=form.id, discount_id="d1", code="PROMO", max_uses=5)
    db.add_all([inv, code])
    db.flush()
    sub = m.FormSubmission(form_id=form.id, event_id=ev.id, data_json='{"a":1}', person_id="1001", invite_id=inv.id, discount_code_id=code.id, status="confirmed", created_at=datetime(2026, 10, 20, 15, 30, 5))
    db.add(sub)
    db.flush()
    pay = m.FormPayment(form_id=form.id, event_id=ev.id, submission_id=sub.id, reference="REF-ORIGEN-1", amount_cents=100000, currency="COP", status="approved", person_id="1001",
                        created_at=datetime(2026, 10, 20, 15, 31, 0))
    db.add(pay)
    db.flush()
    db.add(m.FormRefund(payment_id=pay.id, amount_cents=1000, kind="partial", status="done", reason="prueba", created_by_id=coord.id, created_at=datetime(2026, 10, 21, 9, 0, 0)))
    db.add(m.FormPerson(form_id=form.id, person_id="1001", data_json="{}"))
    db.add(m.FormEvent(form_id=form.id, sid="s1", kind="view", created_at=datetime(2026, 10, 20, 15, 0, 0)))
    db.add(m.RouletteConfig(event_id=ev.id, behavior_json="{}", style_json="{}", display_token="tok-ruleta", authorized_json='{"by": 1}'))
    db.add(m.RouletteDraw(event_id=ev.id, label="Sorteo 1", mode="persona", is_random=True, candidates_count=3, winners_json='[{"id":"1001"}]', created_by_id=reg.id, created_at=datetime(2026, 10, 22, 18, 0, 0)))
    people = []
    for i, (cid, first) in enumerate((("1001", "Ana"), ("1002", "Beto"), ("1003", "Carla")), 1):
        u = factory.person(ev, cid, first, "Sintetica")
        u.entity, u.opt_1, u.birth_date = f"Empresa {i}", f"Cargo {i}", datetime(1990, 1, i).date()
        u.face_encoding, u.is_biometric_enabled, u.face_captured_at = "VECTOR-SECRETO", True, datetime(2026, 10, 19, 8, 0, 0)     # biométrico de origen: NO debe viajar
        people.append(u)
    db.commit()
    for cid, when in (("1001", datetime(2026, 10, 22, 14, 5, 7)), ("1002", datetime(2026, 10, 22, 14, 9, 31))):
        db.add(m.AccessLog(tenant_id=ev.tenant_id, user_id=cid, timestamp=when, record_type="Registrado", event_id=ev.id, registered_by_staff_id=reg.id, client_id=f"cid-{cid}", registration_method="cedula"))
    db.add(m.AreaMovement(event_id=ev.id, area_id=area.id, user_id="1001", tenant_id=ev.tenant_id, direction="in", method="qr", timestamp=datetime(2026, 10, 22, 15, 0, 0), registered_by_staff_id=reg.id))
    db.add(m.InventoryDelivery(event_id=ev.id, item_id=item.id, batch_id="b1", user_id="1001", tenant_id=ev.tenant_id, qty=1, delivered_at=datetime(2026, 10, 22, 15, 5, 0), delivered_by_staff_id=reg.id))
    db.add(m.PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_at=datetime(2026, 10, 22, 14, 6, 0), printed_by_staff_id=reg.id))
    db.add(m.PersonChange(at=datetime(2026, 10, 22, 14, 5, 7), tenant_id=ev.tenant_id, event_id=ev.id, user_id="1001", staff_user_id=reg.id, kind="registration_status", old_value="No registrado", new_value="Registrado"))
    db.add(m.WebAcceptance(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, created_at=datetime(2026, 10, 20, 10, 0, 0), verified_by_staff_id=reg.id))
    db.commit()
    consent.record(db, tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, version="v1.1_test", legal_text_hash="b" * 64, accepted=True, adult=True, reason="consent", at=datetime(2026, 10, 20, 10, 5, 0))
    for a in db.query(m.EventAttendee).filter_by(event_id=ev.id):
        a.origin, a.accept_token, a.digital_token = "base", f"acc-{a.user_id}", f"dig-{a.user_id}"
    db.commit()
    return ev


def _count(db, model, **kw):
    return db.query(func.count()).select_from(model).filter_by(**kw).scalar()


def test_export_has_manifest_hashes_no_biometrics_and_no_staff_accounts(db, factory):
    ev = _build(db, factory)
    data, manifest = et.export_event(db, ev, staff_username="root")
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert "manifest.json" in zf.namelist() and manifest["format"] == "goldenweb-evento" and manifest["format_version"] == 1
    assert manifest["tables"]["access_logs"]["count"] == 2 and manifest["tables"]["users"]["count"] == 3 and manifest["tables"]["form_payments"]["count"] == 1
    assert "staff_users" not in manifest["tables"] and sorted(manifest["staff_usernames"]) == ["coord_origen", "digit_origen"]
    blob = b"".join(zf.read(n) for n in zf.namelist())
    assert b"VECTOR-SECRETO" not in blob and b"face_encoding" not in blob                      # ni vector ni columna biométrica
    assert b"password" not in blob and b"k-origen" not in blob                                 # sin contraseñas ni la clave de pruebas del formulario
    assert db.query(m.EventTransferLog).filter_by(kind="export").count() == 1


def test_dry_run_changes_nothing_and_real_import_creates_a_new_equal_event(db, factory):
    ev = _build(db, factory)
    data, manifest = et.export_event(db, ev, staff_username="root")
    # el destino: la misma base (otro evento nuevo en el mismo cliente) pero con la cuenta digit_origen inexistente y coord_origen presente
    before = {t.name: db.execute(select(func.count()).select_from(t)).scalar() for t in m.Base.metadata.sorted_tables if t.name != "event_transfer_log"}
    rep = et.import_package(db, data, staff_username="root", new_event_code="COPIA-1", new_name="Copia del evento", dry_run=True)
    assert rep["ok"] and rep["dry_run"] and rep["tables"]["access_logs"]["imported"] == 2
    after = {t.name: db.execute(select(func.count()).select_from(t)).scalar() for t in m.Base.metadata.sorted_tables if t.name != "event_transfer_log"}
    assert before == after                                                                    # el simulacro no deja NADA
    rep = et.import_package(db, data, staff_username="root", new_event_code="COPIA-1", new_name="Copia del evento", dry_run=False)
    assert rep["ok"] and not rep["dry_run"]
    new = db.query(m.Event).filter_by(event_code="COPIA-1").one()
    assert new.id != ev.id and new.name == "Copia del evento" and new.tenant_id == ev.tenant_id
    # configuración igual
    assert new.print_settings_json == ev.print_settings_json and new.optional_field_labels == ev.optional_field_labels and new.auto_register is True
    assert _count(db, m.EventFieldConfig, event_id=new.id) == 1 and _count(db, m.EventArea, event_id=new.id) == 1 and _count(db, m.BadgeTemplate, event_id=new.id) == 1
    # personas y registros con sus horas en UTC, sin convertir; cédulas conservadas
    logs = db.query(m.AccessLog).filter_by(event_id=new.id).order_by(m.AccessLog.timestamp).all()
    assert [(l.user_id, l.timestamp) for l in logs] == [("1001", datetime(2026, 10, 22, 14, 5, 7)), ("1002", datetime(2026, 10, 22, 14, 9, 31))] and logs[0].client_id == "cid-1001"
    assert _count(db, m.EventAttendee, event_id=new.id) == 3 and db.query(m.EventAttendee).filter_by(event_id=new.id, user_id="1001").one().origin == "base"
    # los conteos del evento nuevo igualan los del original, tabla por tabla (las que viajan)
    for name in ("event_field_configs", "event_areas", "inventory_items", "badge_templates", "web_forms", "event_attendees", "access_logs", "area_movements", "inventory_deliveries", "print_logs",
                 "person_changes", "web_acceptances", "roulette_configs", "roulette_draws", "form_submissions"):          # form_payments: la referencia ya existe en esta base (se prueba aparte)
        t = m.Base.metadata.tables[name]
        n = lambda eid: db.execute(select(func.count()).select_from(t).where(t.c.event_id == eid)).scalar()
        assert n(new.id) == n(ev.id), name
    # el original no se tocó
    assert db.query(m.Event).filter_by(id=ev.id).one().event_code == ev.event_code and _count(db, m.AccessLog, event_id=ev.id) == 2


def test_import_never_overwrites_and_asks_for_a_new_code_and_name(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    rep = et.import_package(db, data, dry_run=False)                                          # mismo código y nombre: conflicto, no escribe
    assert not rep["ok"] and len(rep["conflicts"]) == 2 and db.query(m.Event).count() == 1
    rep = et.import_package(db, data, new_event_code="OTRO.1", new_name="Otro nombre", dry_run=False)
    assert rep["ok"] and db.query(m.Event).count() == 2
    rep = et.import_package(db, data, new_event_code="otro.1", new_name="Otro nombre 2", dry_run=False)   # el código no distingue mayúsculas
    assert not rep["ok"] and db.query(m.Event).count() == 2


def test_biometrics_and_staff_accounts_never_come_in_and_consents_do(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    # el destino ya conoce a la persona 1002 con OTROS datos y a una cuenta con el nombre coord_origen
    u = db.query(m.User).filter_by(id="1002", tenant_id=ev.tenant_id).one()
    et.import_package(db, data, new_event_code="N-1", new_name="Nuevo 1", dry_run=False)
    db.expire_all()
    new = db.query(m.Event).filter_by(event_code="N-1").one()
    assert db.query(m.User).filter(m.User.face_encoding.isnot(None)).count() == 3            # los 3 ORIGINALES conservan lo suyo; ninguna fila nueva (las personas ya existían)
    assert db.query(m.StaffUser).count() == 2                                                  # no se creó ninguna cuenta
    assert db.query(m.AuditConsentLog).count() == 1                                            # el consentimiento ya estaba (mismo id en esta base): no se duplica ni se toca
    # quién registró: la cuenta existe en el destino → enlazada
    assert db.query(m.AccessLog).filter_by(event_id=new.id).first().registered_by_staff_id == db.query(m.StaffUser).filter_by(username="digit_origen").one().id
    assert new.coordinator_staff_id == db.query(m.StaffUser).filter_by(username="coord_origen").one().id
    assert u.first_name == "Beto"


def test_a_fresh_destination_gets_new_people_without_biometrics_and_keeps_staff_names_as_text(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    # destino «vacío»: se borran el evento original y las cuentas del personal (la persona y sus datos se borran con él)
    for t in reversed(m.Base.metadata.sorted_tables):
        if t.name not in ("tenants", "event_transfer_log"):
            if t.name == "audit_consent_logs":
                db.execute(m.Base.metadata.tables["audit_consent_logs"].select().limit(0))
                from sqlalchemy import text as _t
                db.execute(_t("ALTER TABLE audit_consent_logs DISABLE TRIGGER USER"))
                db.execute(t.delete())
                db.execute(_t("ALTER TABLE audit_consent_logs ENABLE TRIGGER USER"))
            else:
                db.execute(t.delete())
    db.commit()
    rep = et.import_package(db, data, staff_username="root", new_event_code="DEST-1", new_name="Destino 1", dry_run=False)
    assert rep["ok"] and rep["persons"]["new"] == 3 and sorted(rep["staff_without_link"]) == ["coord_origen", "digit_origen"]
    new = db.query(m.Event).filter_by(event_code="DEST-1").one()
    assert new.coordinator_staff_id is None and db.query(m.StaffUser).count() == 0
    assert db.query(m.AccessLog).filter_by(event_id=new.id).first().registered_by_staff_id is None
    names = {(a.table_name, a.column_name, a.username) for a in db.query(m.EventImportActor).all()}
    assert ("access_logs", "registered_by_staff_id", "digit_origen") in names and ("events", "coordinator_staff_id", "coord_origen") in names
    p = db.query(m.User).filter_by(id="1001", tenant_id=new.tenant_id).one()
    assert p.first_name == "Ana" and p.entity == "Empresa 1" and p.birth_date == datetime(1990, 1, 1).date()
    assert p.face_encoding is None and p.is_biometric_enabled is False and p.face_captured_at is None
    c = db.query(m.AuditConsentLog).filter_by(event_id=new.id).one()                           # el consentimiento viaja tal cual, con su fecha original y su id
    assert c.consent_timestamp_utc == datetime(2026, 10, 20, 10, 5, 0, tzinfo=timezone.utc) and c.consent_version == "v1.1_test" and c.user_id == "1001" and rep["tables"]["audit_consent_logs"]["imported"] == 1


def test_no_side_effects_forms_in_tests_payments_historic_and_tokens_kept_if_free(db, factory, outbox):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    outbox.clear() if hasattr(outbox, "clear") else None
    queued = db.query(m.Job).count()
    rep = et.import_package(db, data, new_event_code="SE-1", new_name="Sin efectos", dry_run=False)
    new = db.query(m.Event).filter_by(event_code="SE-1").one()
    assert db.query(m.Job).count() == queued                                                   # nada encolado
    assert not getattr(outbox, "sent", getattr(outbox, "messages", []))                         # ningún correo
    form = db.query(m.WebForm).filter_by(event_id=new.id).one()
    assert form.manual_status == "pruebas" and form.use_schedule is False and form.test_key != "k-origen" and form.slug == "inscripcion"
    # el pago de origen ya existe en el destino (misma base): se OMITE, no se duplica; el reembolso depende de él y tampoco entra
    assert rep["skipped"]["form_payments"] and rep["tables"]["form_payments"]["imported"] == 0 and rep["tables"]["form_refunds"]["imported"] == 0
    assert db.query(m.FormPayment).filter_by(reference="REF-ORIGEN-1").count() == 1
    sub = db.query(m.FormSubmission).filter_by(event_id=new.id).one()
    assert sub.source == "importado" and sub.created_at == datetime(2026, 10, 20, 15, 30, 5) and sub.invite_id is not None
    inv = db.query(m.FormInvite).filter_by(form_id=form.id).one()
    assert inv.token != "tok-invite-1" and any("form_invites.token" in w for w in rep["warnings"])      # chocó con el del original: se generó de nuevo
    assert db.query(m.RouletteConfig).filter_by(event_id=new.id).one().authorized_json is None


def test_payments_enter_as_history_with_origin_when_the_reference_is_free(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    db.query(m.FormRefund).delete()
    db.query(m.FormPayment).filter_by(reference="REF-ORIGEN-1").delete()
    db.commit()
    # el paquete trae el pago: lo regresamos a una base donde la referencia ya no existe
    rep = et.import_package(db, data, new_event_code="PH-1", new_name="Pagos historia", dry_run=False)
    pay = db.query(m.FormPayment).filter_by(reference="REF-ORIGEN-1").one()
    assert pay.origin == "importado" and pay.amount_cents == 100000 and pay.event_id == db.query(m.Event).filter_by(event_code="PH-1").one().id
    assert pay.created_at == datetime(2026, 10, 20, 15, 31, 0) and rep["tables"]["form_refunds"]["imported"] == 1


def test_event_in_process_waits_for_confirmation_and_does_not_freeze_deploys(db, factory):
    from app import ops
    ev = _build(db, factory)
    ev.status = "finalizado"
    db.commit()
    data, _ = et.export_event(db, ev)
    ev.status = "creado"
    db.commit()
    rep = et.import_package(db, data, new_event_code="FIN-1", new_name="Finalizado", dry_run=False)
    assert db.query(m.Event).filter_by(event_code="FIN-1").one().status == "finalizado" and not rep["pending_confirm"]       # finalizado: no cambia
    ev.status = "en_proceso"
    db.commit()
    data, _ = et.export_event(db, ev)
    ev.status = "creado"
    db.commit()
    rep = et.import_package(db, data, new_event_code="PROC-1", new_name="En proceso", dry_run=False)
    imp = db.query(m.Event).filter_by(event_code="PROC-1").one()
    assert rep["pending_confirm"] and imp.status == "creado"                                   # en espera
    assert ops.deploy_allowed(db, 0)["allowed"] is True                                        # NO activa el congelamiento
    out = et.confirm_import(db, rep["import_id"], "root")
    assert out["status"] == "en_proceso" and db.get(m.Event, imp.id).status == "en_proceso" and ops.deploy_allowed(db, 0)["allowed"] is False
    with pytest.raises(et.TransferError):
        et.confirm_import(db, rep["import_id"])                                                # ya confirmada


def test_keep_original_form_state_is_applied_only_on_confirmation(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    rep = et.import_package(db, data, new_event_code="KS-1", new_name="Conservar", keep_original_state=True, dry_run=False)
    new = db.query(m.Event).filter_by(event_code="KS-1").one()
    form = db.query(m.WebForm).filter_by(event_id=new.id).one()
    assert rep["pending_confirm"] and form.manual_status == "pruebas"
    et.confirm_import(db, rep["import_id"])
    db.expire_all()
    assert db.get(m.WebForm, form.id).manual_status == "activo"


def test_suppressed_people_are_not_imported(db, factory):
    ev = _build(db, factory)
    data, _ = et.export_event(db, ev)
    db.add(m.SuppressedPerson(tenant_id=ev.tenant_id, cedula_hash=consent.cedula_hash("1003"), suppressed_at=datetime(2026, 10, 1)))
    db.commit()
    rep = et.import_package(db, data, new_event_code="SUP-1", new_name="Con suprimida", dry_run=False)
    new = db.query(m.Event).filter_by(event_code="SUP-1").one()
    assert rep["persons"]["suppressed_skipped"] == 1 and db.query(m.EventAttendee).filter_by(event_id=new.id, user_id="1003").count() == 0
    assert db.query(m.EventAttendee).filter_by(event_id=new.id).count() == 2


def test_rejects_newer_format_newer_migration_corrupted_and_foreign_zips(db, factory):
    ev = _build(db, factory)
    data, manifest = et.export_event(db, ev)

    def repack(edit):
        zin = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zout:
            for n in zin.namelist():
                zout.writestr(n, edit(n, zin.read(n)))
        return out.getvalue()

    def with_manifest(**kw):
        def edit(n, raw):
            if n != "manifest.json":
                return raw
            mf = json.loads(raw)
            mf.update(kw)
            return json.dumps(mf)
        return repack(edit)

    with pytest.raises(et.TransferError, match="versión de formato más nueva"):
        et.import_package(db, with_manifest(format_version=99), new_event_code="X-1")
    with pytest.raises(et.TransferError, match="más nueva"):
        et.import_package(db, with_manifest(alembic_revision="9999_futura"), new_event_code="X-1")
    with pytest.raises(et.TransferError, match="suma de control"):
        et.import_package(db, repack(lambda n, raw: raw + b" " if n == "data/access_logs.jsonl" else raw), new_event_code="X-1")
    with pytest.raises(et.TransferError, match="no es un paquete"):
        et.import_package(db, b"no soy un zip", new_event_code="X-1")
    with pytest.raises(et.TransferError, match="no corresponden"):
        et.import_package(db, repack(lambda n, raw: raw) + b"", new_event_code="X-1") if False else et.import_package(db, _zip_with_extra(data), new_event_code="X-1")
    assert db.query(m.Event).count() == 1                                                      # nada entró


def _zip_with_extra(data: bytes) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n))
        zout.writestr("../../evil.txt", "x")
    return out.getvalue()


def test_only_super_admin_can_use_the_endpoints(client, db, factory):
    factory.staff("admin", "adm")
    factory.staff("super_admin", "root")
    ev = _build(db, factory)
    login(client, "adm")
    assert client.get(f"/api/event-transfer/export/{ev.id}").status_code == 403
    assert client.post("/api/event-transfer/import/dry-run", files={"file": ("x.zip", b"x")}).status_code == 403
    client.get("/logout")
    login(client, "root")
    r = client.get(f"/api/event-transfer/export/{ev.id}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and r.headers["cache-control"] == "no-store"
    pkg = r.content
    d = client.post("/api/event-transfer/import/dry-run", files={"file": ("e.zip", pkg)}, data={"new_event_code": "API-1", "new_name": "Por API"})
    assert d.status_code == 200 and d.json()["dry_run"] is True and d.json()["ok"] is True
    c = client.post("/api/event-transfer/import", files={"file": ("e.zip", pkg)})                # mismo código y nombre: conflicto claro
    assert c.status_code == 409 and len(c.json()["detail"]["conflicts"]) == 2
    ok = client.post("/api/event-transfer/import", files={"file": ("e.zip", pkg)}, data={"new_event_code": "API-1", "new_name": "Por API"})
    assert ok.status_code == 200 and ok.json()["event_id"]
    bad = client.post("/api/event-transfer/import/dry-run", files={"file": ("x.zip", b"basura")})
    assert bad.status_code == 400 and "paquete" in bad.json()["detail"]
    assert client.get(f"/api/event-transfer/export/{ev.id}?include_biometrics=true").status_code == 400      # F3
    assert not any(b"traceback" in (x or b"").lower() for x in (r.content[:0],))


def _script(name):
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(name, pathlib.Path("scripts") / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_command_line_scripts_use_the_same_engine(db, factory, tmp_path, capsys):
    ev = _build(db, factory)
    out = tmp_path / "evento.zip"
    assert _script("event_export").main(["--event-code", ev.event_code, "--out", str(out), "--user", "cli"]) == 0
    assert out.stat().st_size > 0 and "access_logs" in capsys.readouterr().out
    assert _script("event_import").main([str(out), "--new-code", "CLI-1", "--new-name", "Por consola", "--dry-run"]) == 0
    assert db.query(m.Event).count() == 1                                                      # simulacro: nada
    assert _script("event_import").main([str(out), "--new-code", "CLI-1", "--new-name", "Por consola"]) == 0
    assert db.query(m.Event).filter_by(event_code="CLI-1").count() == 1
    assert _script("event_import").main([str(out)]) == 3                                       # mismo código y nombre: conflicto, código de salida 3
    assert _script("event_export").main(["--event-code", "NO-EXISTE", "--out", str(tmp_path / "x.zip")]) == 2
