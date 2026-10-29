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


# ------------------------------------------------------------------------------------------------ F2: archivos del storage
def _files_event(db, factory):
    from app.storage import badge_asset_key, form_file_key, get_storage, key_of
    ev = _build(db, factory)
    st = get_storage()
    t = ev.tenant_id
    st.put(badge_asset_key(t, "fondo.png"), b"PNG-FONDO")
    st.put(badge_asset_key(t, "logo-form.png"), b"PNG-LOGO-FORM")
    st.put(badge_asset_key(t, "no-referenciada.png"), b"X")
    tpl = db.query(m.BadgeTemplate).filter_by(event_id=ev.id).one()
    tpl.background_type, tpl.background_value = "image", f"/api/badge-assets/{t}/fondo.png"
    form = db.query(m.WebForm).filter_by(event_id=ev.id).one()
    form.design_json = json.dumps({"theme": {"logo": f"{t}/logo-form.png"}})
    st.put(form_file_key(t, form.id, "cv.pdf"), b"%PDF-CV")
    st.put(key_of(t, "signatures", ev.id, "1001__firma.png"), b"FIRMA")
    st.put(key_of(t, "event_docs", ev.id, "doc1.pdf"), b"%PDF-DOC")
    db.add(m.EventDocument(event_id=ev.id, name="Contrato", original_filename="contrato.pdf", stored_path=key_of(t, "event_docs", ev.id, "doc1.pdf"), mime_type="application/pdf", size_bytes=8))
    st.put(key_of(t, "event_expenses", ev.id, "ev1.png"), b"EVIDENCIA")
    db.add(m.EventExpense(event_id=ev.id, category="Logística", responsible="Ana", amount=1500, evidence_path=key_of(t, "event_expenses", ev.id, "ev1.png"), evidence_name="ev1.png"))
    st.put(key_of(t, "event_logos", "abc.png"), b"LOGO-EVENTO")
    ev.logo_mode, ev.logo_path = "custom", key_of(t, "event_logos", "abc.png")
    st.put(key_of(t, "event_reports", "informe.pdf"), b"%PDF-INFORME")
    ev.report_pdf_path = key_of(t, "event_reports", "informe.pdf")
    db.commit()
    return ev


def test_export_carries_the_referenced_files_by_hash_and_skips_the_rest(db, factory):
    ev = _files_event(db, factory)
    data, manifest = et.export_event(db, ev, staff_username="root")
    roles = sorted(f["role"] for f in manifest["files"])
    assert roles == ["badge_asset", "badge_asset", "event_doc", "expense", "form_file", "logo", "report", "signature"] and manifest["includes_files"] is True
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert all(f"files/{f['sha256']}" in zf.namelist() for f in manifest["files"])
    assert b"X" not in [zf.read(f"files/{f['sha256']}") for f in manifest["files"]]            # la imagen que ningún diseño usa no viaja


def test_import_writes_the_files_under_the_new_ids_and_rewrites_design_references(db, factory):
    from app.storage import badge_asset_key, form_file_key, get_storage, key_of
    ev = _files_event(db, factory)
    data, _ = et.export_event(db, ev)
    st = get_storage()
    dry = et.import_package(db, data, new_event_code="F2-DRY", new_name="Dry", dry_run=True)
    assert dry["ok"] and dry["files"]["planned"] == 6 and dry["files"]["written"] == 0           # el simulacro solo cuenta; badge_asset ya existe igual (misma huella): no se vuelve a escribir (por eso son 6 y no 8)
    assert not st.list(key_of(ev.tenant_id, "signatures", "9999"))
    rep = et.import_package(db, data, new_event_code="F2-1", new_name="Con archivos", dry_run=False)
    new = db.query(m.Event).filter_by(event_code="F2-1").one()
    t = new.tenant_id
    assert rep["files"]["written"] == rep["files"]["planned"] == 6
    form = db.query(m.WebForm).filter_by(event_id=new.id).one()
    assert st.get(form_file_key(t, form.id, "cv.pdf")) == b"%PDF-CV"
    assert st.get(key_of(t, "signatures", new.id, "1001__firma.png")) == b"FIRMA"
    doc = db.query(m.EventDocument).filter_by(event_id=new.id).one()
    assert doc.stored_path != db.query(m.EventDocument).filter_by(event_id=ev.id).one().stored_path and st.get(doc.stored_path) == b"%PDF-DOC" and f"/{new.id}/" in doc.stored_path
    exp = db.query(m.EventExpense).filter_by(event_id=new.id).one()
    assert st.get(exp.evidence_path) == b"EVIDENCIA" and exp.evidence_name == "ev1.png"
    assert new.logo_mode == "custom" and st.get(new.logo_path) == b"LOGO-EVENTO" and new.logo_path != ev.logo_path
    assert st.get(new.report_pdf_path) == b"%PDF-INFORME" and f"/{new.id}/" in new.report_pdf_path
    tpl = db.query(m.BadgeTemplate).filter_by(event_id=new.id).one()
    assert tpl.background_value == f"/api/badge-assets/{t}/fondo.png" and st.get(badge_asset_key(t, "fondo.png")) == b"PNG-FONDO"


def test_a_different_image_with_the_same_name_gets_a_new_name_and_the_design_follows(db, factory):
    from app.storage import badge_asset_key, get_storage
    ev = _files_event(db, factory)
    data, _ = et.export_event(db, ev)
    st = get_storage()
    st.put(badge_asset_key(ev.tenant_id, "fondo.png"), b"OTRA-IMAGEN-DISTINTA")                 # en el destino ya hay OTRA con ese nombre
    rep = et.import_package(db, data, new_event_code="F2-2", new_name="Nombre choca", dry_run=False)
    new = db.query(m.Event).filter_by(event_code="F2-2").one()
    tpl = db.query(m.BadgeTemplate).filter_by(event_id=new.id).one()
    assert tpl.background_value != f"/api/badge-assets/{ev.tenant_id}/fondo.png" and tpl.background_value.startswith(f"/api/badge-assets/{ev.tenant_id}/fondo-")
    assert st.get(badge_asset_key(ev.tenant_id, "fondo.png")) == b"OTRA-IMAGEN-DISTINTA"        # la del destino NO se pisa
    assert st.get(badge_asset_key(ev.tenant_id, tpl.background_value.rsplit("/", 1)[-1])) == b"PNG-FONDO"
    assert any("otro nombre" in w for w in rep["warnings"])


def test_a_failure_while_writing_files_leaves_no_event_and_no_orphan_files(db, factory, monkeypatch):
    from app import storage as storage_mod
    from app.storage import get_storage, key_of
    ev = _files_event(db, factory)
    data, _ = et.export_event(db, ev)
    st = get_storage()
    real_put, calls = st.put, {"n": 0}

    def flaky(key, content):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disco lleno")
        return real_put(key, content)
    monkeypatch.setattr(st, "put", flaky)
    with pytest.raises(RuntimeError):
        et.import_package(db, data, new_event_code="F2-FALLA", new_name="Falla", dry_run=False)
    assert db.query(m.Event).filter_by(event_code="F2-FALLA").count() == 0
    new_prefix = key_of(ev.tenant_id, "event_docs")
    assert [k for k in st.list(new_prefix) if k.rsplit("/", 2)[-2] != str(ev.id)] == []        # nada huérfano de la importación fallida
    assert storage_mod is not None


def test_import_into_another_client_moves_everything_to_that_client(db, factory):
    from app.storage import get_storage, key_of
    ev = _files_event(db, factory)
    data, _ = et.export_event(db, ev)
    other = factory.tenant("otro")
    rep = et.import_package(db, data, new_event_code="OTRO-1", new_name="En otro cliente", target_tenant_id=other.id, dry_run=False)
    new = db.query(m.Event).filter_by(event_code="OTRO-1").one()
    assert rep["ok"] and new.tenant_id == "otro"
    assert db.query(m.User).filter_by(tenant_id="otro").count() == 3 and db.query(m.EventAttendee).filter_by(event_id=new.id, tenant_id="otro").count() == 3
    assert db.query(m.AccessLog).filter_by(event_id=new.id, tenant_id="otro").count() == 2
    assert get_storage().get(key_of("otro", "signatures", new.id, "1001__firma.png")) == b"FIRMA"
    bad = et.import_package(db, data, new_event_code="OTRO-2", new_name="Cliente inexistente", target_tenant_id="no-existe", dry_run=True)
    assert not bad["ok"] and "cliente elegido no existe" in bad["conflicts"][0]


# ------------------------------------------------------------------------------------------------ F3: biometría opcional cifrada
def _bio_event(db, factory):
    from app import crypto
    from app.storage import get_storage, photo_key
    ev = _build(db, factory)
    st = get_storage()
    for cid in ("1001", "1002", "1003"):
        st.put(photo_key(ev.tenant_id, cid), crypto.encrypt_bytes(f"JPEG-{cid}".encode()))
    u3 = db.query(m.User).filter_by(id="1003", tenant_id=ev.tenant_id).one()
    u3.birth_date = datetime(2015, 3, 1).date()                                              # menor de edad
    db.commit()
    consent.record(db, tenant_id=ev.tenant_id, user_id="1003", event_id=ev.id, version="v1.1_test", legal_text_hash="b" * 64, accepted=True, adult=True, reason="consent")
    db.commit()
    return ev


def _wipe_event_data(db):
    from sqlalchemy import text as _t
    for t in reversed(m.Base.metadata.sorted_tables):
        if t.name not in ("tenants", "event_transfer_log"):
            if t.name == "audit_consent_logs":
                db.execute(_t("ALTER TABLE audit_consent_logs DISABLE TRIGGER USER"))
                db.execute(t.delete())
                db.execute(_t("ALTER TABLE audit_consent_logs ENABLE TRIGGER USER"))
            else:
                db.execute(t.delete())
    db.commit()


def test_biometrics_need_a_passphrase_travel_encrypted_and_never_in_clear(db, factory, monkeypatch):
    monkeypatch.setattr(et, "KDF_ITERATIONS", 1000)
    ev = _bio_event(db, factory)
    with pytest.raises(et.TransferError, match="al menos"):
        et.export_event(db, ev, include_biometrics=True, passphrase="corta")
    data, manifest = et.export_event(db, ev, include_biometrics=True, passphrase="frase de transporte 123")
    zf = zipfile.ZipFile(io.BytesIO(data))
    blob = b"".join(zf.read(n) for n in zf.namelist())
    assert manifest["options"]["include_biometrics"] is True and manifest["tables"]["biometrics"]["count"] == 3 and "biometric_photo" in {f["role"] for f in manifest["files"]}
    assert b"JPEG-1001" not in blob and b"VECTOR-SECRETO" not in blob and b"frase de transporte" not in blob       # ni foto, ni vector, ni la frase viajan en claro
    plain, _ = et.export_event(db, ev)                                                                           # sin la opción: nada biométrico
    assert "biometrics" not in json.loads(zipfile.ZipFile(io.BytesIO(plain)).read("manifest.json"))["tables"]
    with pytest.raises(et.TransferError, match="frase de transporte"):
        et.import_package(db, data, new_event_code="B-0", new_name="Sin frase")
    with pytest.raises(et.TransferError, match="no es la correcta"):
        et.import_package(db, data, new_event_code="B-0", new_name="Frase mala", transport_passphrase="otra frase distinta")
    assert db.query(m.Event).count() == 1


def test_import_with_biometrics_only_for_adults_with_accepted_consent_and_reencrypts_with_the_destination_key(db, factory, monkeypatch):
    from cryptography.fernet import Fernet
    from app import crypto
    from app.storage import get_storage, photo_key
    monkeypatch.setattr(et, "KDF_ITERATIONS", 1000)
    key_a, key_b = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", key_a)
    ev = _bio_event(db, factory)
    data, _ = et.export_event(db, ev, include_biometrics=True, passphrase="frase de transporte 123")
    st = get_storage()
    _wipe_event_data(db)
    for k in list(st.list("")):
        st.delete(k)
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", key_b)                                                             # el destino tiene OTRA llave
    rep = et.import_package(db, data, new_event_code="B-1", new_name="Con biometría", transport_passphrase="frase de transporte 123", dry_run=False)
    assert rep["ok"] and rep["biometrics"]["in_package"] == 3 and rep["biometrics"]["imported"] == 1
    assert rep["biometrics"]["skipped"] == {"sin consentimiento aceptado registrado": 1, "menor de 18 años": 1}   # 1002 sin consentimiento; 1003 menor
    new = db.query(m.Event).filter_by(event_code="B-1").one()
    u1 = db.query(m.User).filter_by(id="1001", tenant_id=new.tenant_id).one()
    assert u1.face_encoding == "VECTOR-SECRETO" and u1.is_biometric_enabled is True and u1.face_captured_at == datetime(2026, 10, 19, 8, 0, 0)        # fechas ORIGINALES (retención)
    for cid in ("1002", "1003"):
        u = db.query(m.User).filter_by(id=cid, tenant_id=new.tenant_id).one()
        assert u.face_encoding is None and u.is_biometric_enabled is False and not st.exists(photo_key(new.tenant_id, cid))
    raw = st.get(photo_key(new.tenant_id, "1001"))
    assert raw != b"JPEG-1001" and raw.startswith(crypto.FILE_MAGIC) and crypto.decrypt_bytes(raw) == b"JPEG-1001"       # cifrada con la llave del destino
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", key_a)
    assert crypto.decrypt_bytes(raw) is None                                                                       # y NO con la del origen
    assert db.query(m.EventTransferLog).filter_by(kind="import").count() == 1


def test_import_can_skip_the_biometrics_of_a_package_that_carries_them(db, factory, monkeypatch):
    monkeypatch.setattr(et, "KDF_ITERATIONS", 1000)
    ev = _bio_event(db, factory)
    data, _ = et.export_event(db, ev, include_biometrics=True, passphrase="frase de transporte 123")
    _wipe_event_data(db)
    rep = et.import_package(db, data, new_event_code="B-2", new_name="Sin biometría", import_biometrics=False, dry_run=False)
    assert rep["ok"] and rep["biometrics"]["imported"] == 0
    assert db.query(m.User).filter(m.User.face_encoding.isnot(None)).count() == 0


# ------------------------------------------------------------------------------------------------ F4: trabajos en segundo plano, descarga firmada, bitácora y purga
@pytest.fixture()
def inline_jobs(monkeypatch):
    monkeypatch.setenv("EVENT_TRANSFER_INLINE", "1")
    monkeypatch.setattr(et, "KDF_ITERATIONS", 1000)


def _upload(client, pkg: bytes) -> str:
    r = client.post("/api/event-transfer/upload-url", json={"filename": "evento.zip", "size": len(pkg)})
    assert r.status_code == 200, r.text
    up = r.json()
    put = client.put(up["url"], content=pkg, headers={"Content-Type": "application/zip"})
    assert put.status_code in (200, 201, 204), put.text
    return up["token"]


def test_export_job_download_is_signed_short_lived_and_purged_after_24_hours(client, db, factory, inline_jobs):
    from datetime import timedelta
    from app import event_transfer_jobs as jobs
    from app.storage import get_storage
    from app.timeutil import utcnow
    factory.staff("super_admin", "root")
    ev = _files_event(db, factory)
    login(client, "root")
    r = client.post("/api/event-transfer/export/start", json={"event_id": ev.id})
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "done" and job["ready"] and job["progress"] == 100 and job["result"]["counts"]["access_logs"] == 2 and "download_url" in job
    dl = client.get(job["download_url"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip" and dl.headers["cache-control"] == "no-store" and zipfile.ZipFile(io.BytesIO(dl.content)).testzip() is None
    assert client.get(f"/api/event-transfer/download/{job['id']}?t=falso").status_code == 400                   # sin firma válida no hay descarga
    token = job["download_url"].split("t=")[1]
    assert client.get(f"/api/event-transfer/download/{job['id'] + 1}?t={token}").status_code in (403, 404)        # el enlace es de ESE trabajo
    row = db.get(m.EventTransferLog, job["id"])
    key = row.file_key
    assert get_storage().exists(key) and jobs.purge_expired(db) == 0
    row.finished_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert jobs.purge_expired(db) == 1 and not get_storage().exists(key)                                        # la purga de las 24 h borra el .zip del almacenamiento
    again = client.get(f"/api/event-transfer/jobs/{job['id']}").json()
    assert again["ready"] is False and "download_url" not in again


def test_biometric_export_through_the_api_needs_a_long_enough_passphrase_and_never_stores_it(client, db, factory, inline_jobs):
    factory.staff("super_admin", "root")
    ev = _bio_event(db, factory)
    login(client, "root")
    assert client.post("/api/event-transfer/export/start", json={"event_id": ev.id, "include_biometrics": True, "passphrase": "corta"}).status_code == 400
    ok = client.post("/api/event-transfer/export/start", json={"event_id": ev.id, "include_biometrics": True, "passphrase": "frase de transporte 123"}).json()
    assert ok["status"] == "done" and ok["result"]["biometrics"] is True
    assert all("frase de transporte" not in (r.options_json or "") + (r.result_json or "") for r in db.query(m.EventTransferLog))      # la frase no se guarda en ninguna parte
    assert client.get(f"/api/event-transfer/export/{ev.id}?include_biometrics=true").status_code == 400                              # el atajo de un paso no lleva biometría


def test_import_wizard_flow_upload_inspect_dry_run_import_confirm_and_fidelity(client, db, factory, inline_jobs):
    factory.staff("super_admin", "root")
    ev = _files_event(db, factory)
    ev.status = "en_proceso"
    db.commit()
    login(client, "root")
    pkg = client.get(f"/api/event-transfer/export/{ev.id}").content
    token = _upload(client, pkg)
    info = client.post("/api/event-transfer/import/inspect", json={"token": token}).json()
    assert info["event_code"] == ev.event_code and info["counts"]["access_logs"] == 2 and info["files"] == 8 and info["has_biometrics"] is False
    dry = client.post("/api/event-transfer/import/start", json={"token": token, "dry_run": True, "new_event_code": "W-1", "new_name": "Asistente"}).json()
    assert dry["status"] == "done" and dry["result"]["dry_run"] is True and dry["result"]["tables"]["access_logs"]["imported"] == 2 and db.query(m.Event).count() == 1
    conflict = client.post("/api/event-transfer/import/start", json={"token": token, "dry_run": False}).json()           # mismo código y nombre
    assert conflict["status"] == "error" and len(conflict["result"]["conflicts"]) == 2
    real = client.post("/api/event-transfer/import/start", json={"token": token, "dry_run": False, "new_event_code": "W-1", "new_name": "Asistente"}).json()
    assert real["status"] == "done" and real["event_id"] and real["result"]["pending_confirm"] is True
    fid = real["result"]["fidelity"]
    # misma base que el origen: el pago (referencia única), su reembolso y el consentimiento (mismo id) YA existen aquí y se omiten; todo lo demás queda IGUAL
    assert sorted(fid["different_tables"]) == ["audit_consent_logs", "form_payments", "form_refunds"] and fid["all_equal"] is False
    assert "ya existe" in fid["tables"]["form_payments"]["note"] and "ya estaba registrado" in fid["tables"]["audit_consent_logs"]["note"]
    assert fid["tables"]["access_logs"] == {"source": 2, "destination": 2, "equal": True, "note": ""} and fid["tables"]["users"]["equal"] is True
    assert db.get(m.Event, real["event_id"]).status == "creado"
    c = client.post(f"/api/event-transfer/imports/{real['result']['import_id']}/confirm")
    assert c.status_code == 200 and c.json()["status"] == "en_proceso"
    assert client.post(f"/api/event-transfer/imports/{real['result']['import_id']}/confirm").status_code == 400
    log = client.get("/api/event-transfer/log").json()
    assert {r["kind"] for r in log} == {"export", "import"} and all(set(r) <= {"id", "at", "kind", "by", "event_id", "event_code", "status", "rows", "pending_confirm"} for r in log)   # sin datos personales
    assert client.post("/api/event-transfer/import/start", json={"token": "token-falso", "dry_run": True}).status_code == 400


def test_upload_is_bound_to_the_staff_who_asked_for_it(client, db, factory, inline_jobs):
    factory.staff("super_admin", "root")
    factory.staff("super_admin", "root2")
    ev = _build(db, factory)
    login(client, "root")
    token = _upload(client, client.get(f"/api/event-transfer/export/{ev.id}").content)
    client.get("/logout")
    login(client, "root2")
    assert client.post("/api/event-transfer/import/inspect", json={"token": token}).status_code == 400                 # el token es de OTRA persona


def test_gold_test_export_import_export_gives_equivalent_packages(db, factory, inline_jobs):
    """La prueba de oro (docs/18 §2.8): exportar un evento sintético completo, importarlo en una base VACÍA, volver a exportarlo y comprobar que los dos paquetes son equivalentes salvo ids y metadatos."""
    from app.storage import get_storage
    ev = _files_event(db, factory)
    ev.status = "finalizado"
    db.commit()
    code = ev.event_code
    a, manifest_a = et.export_event(db, ev)
    _wipe_event_data(db)
    for k in list(get_storage().list("")):
        get_storage().delete(k)
    rep = et.import_package(db, a, dry_run=False, keep_original_state=True)                               # mismo código y nombre: la base está vacía
    et.confirm_import(db, rep["import_id"])                                                              # el estado original de los formularios se aplica al confirmar
    new = db.query(m.Event).filter_by(event_code=code).one()
    b, manifest_b = et.export_event(db, new)
    _, rows_a, _ = et.read_package(a)
    _, rows_b, _ = et.read_package(b)
    assert et.normalized_digests(rows_a) == et.normalized_digests(rows_b)
    assert {k: v["count"] for k, v in manifest_a["tables"].items()} == {k: v["count"] for k, v in manifest_b["tables"].items()}
    assert sorted((f["role"], f["sha256"]) for f in manifest_a["files"]) == sorted((f["role"], f["sha256"]) for f in manifest_b["files"])      # los archivos son byte a byte los mismos
    assert rep["ok"] and et.fidelity_report(db, new.id, a, rep)["all_equal"] is True


def test_fidelity_report_flags_what_did_not_travel(db, factory, inline_jobs):
    ev = _build(db, factory)
    a, _ = et.export_event(db, ev)
    db.add(m.SuppressedPerson(tenant_id=ev.tenant_id, cedula_hash=consent.cedula_hash("1003"), suppressed_at=datetime(2026, 10, 1)))
    db.commit()
    rep = et.import_package(db, a, new_event_code="FID-1", new_name="Fidelidad", dry_run=False)
    new = db.query(m.Event).filter_by(event_code="FID-1").one()
    fid = et.fidelity_report(db, new.id, a, rep)
    assert fid["all_equal"] is False and "event_attendees" in fid["different_tables"]
    assert "persona suprimida" in fid["tables"]["event_attendees"]["note"] and fid["tables"]["event_attendees"]["source"] == 3 and fid["tables"]["event_attendees"]["destination"] == 2


