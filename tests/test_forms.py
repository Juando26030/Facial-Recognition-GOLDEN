"""Formularios Web: administración, estados, cupo, seguridad, pre-llenado, archivos, carga a la base y reporte (Sprint 5)."""
import io
import json
from datetime import datetime, timedelta

import pytest

from app import formlib as fl
from tests.conftest import login


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (not e.endswith("@dominio-falso.com"), "el dominio no existe"))


def _event(client, factory, **extra):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", **extra)
    login(client, "coord1")
    return ev


def _create(client, ev, name="Feria 2026"):
    """Crea el formulario y le deja los 4 campos básicos con ids FIJOS (cedula, nombres, apellidos, correo) para escribir pruebas legibles."""
    r = client.post(f"/api/events/{ev.id}/forms", json={"name": name})
    assert r.status_code == 200, r.text
    form = r.json()
    r = client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"design": _design(_basic_fields())})
    assert r.status_code == 200, r.text
    return r.json()


def _design(fields, rows=None, theme=None):
    return {"theme": theme or {}, "fields": {f["id"]: f for f in fields}, "rows": rows or [{"items": [f["id"]]} for f in fields]}


def _put(client, ev, form, **body):
    return client.put(f"/api/events/{ev.id}/forms/{form['id']}", json=body)


def _status(client, ev, form, **body):
    return client.put(f"/api/events/{ev.id}/forms/{form['id']}/status", json=body)


def _basic_fields():
    return [
        {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True},
        {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
        {"id": "apellidos", "type": "text_short", "label": "Apellidos", "key": "last_name", "required": True},
        {"id": "correo", "type": "email", "label": "Correo", "key": "email", "required": True},
    ]


def _open(client, ev, form, status="activo", **design_kw):
    if design_kw:
        assert _put(client, ev, form, **design_kw).status_code == 200
    assert _status(client, ev, form, manual_status=status).status_code == 200
    client.post("/logout")


def _url(ev, form):
    return f"/f/{ev.id}/{form['slug']}"


def _submit(client, ev, form, values, token=None, key=None, files=None, **extra):
    payload = {"values": values, "t": token, "k": key, "sid": extra.pop("sid", "s1"), **extra}
    if files:
        return client.post(f"{_url(ev, form)}/submit", data={"data": json.dumps(payload)}, files={f"file:{k}": v for k, v in files.items()})
    return client.post(f"{_url(ev, form)}/submit", json=payload)


def _state(client, ev, form, **params):
    return client.get(f"{_url(ev, form)}/state", params=params).json()


def _person_values():
    return {"cedula": "1001", "nombres": "Ana", "apellidos": "Mora", "correo": "ana@example.com"}


# ------------------------------- administración -------------------------------
def test_create_edit_duplicate_and_delete(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    assert f["slug"] == "feria-2026" and f["manual_status"] == "pruebas" and f["status"] == "pruebas"
    assert {x["key"] for x in f["design"]["fields"].values()} == {"id", "first_name", "last_name", "email"}
    assert "?k=" in f["test_url"] and f["public_url"].endswith(f"/f/{ev.id}/feria-2026")
    assert _create(client, ev)["slug"] == "feria-2026-2"                                   # slug único dentro del evento
    dup = client.post(f"/api/events/{ev.id}/forms/{f['id']}/duplicate").json()
    assert dup["name"] == "Feria 2026 (copia)" and dup["manual_status"] == "pruebas"
    assert len(client.get(f"/api/events/{ev.id}/forms").json()) == 3
    assert client.delete(f"/api/events/{ev.id}/forms/{dup['id']}").status_code == 200
    assert client.get(f"/api/events/{ev.id}/forms/{dup['id']}").status_code == 404


def test_design_is_validated_server_side_with_readable_errors(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    bad = _put(client, ev, f, design=_design([{"id": "a", "type": "select", "label": "X", "options": []}]))
    assert bad.status_code == 400 and "opción" in bad.json()["detail"]
    assert _put(client, ev, f, design=_design([{"id": "a", "type": "text_short", "label": "X", "key": "opcional_7"}])).status_code == 400
    assert _put(client, ev, f, slug="feria-2026").status_code == 200                       # su propio slug no choca consigo mismo
    _create(client, ev, "Otro")
    assert _put(client, ev, f, slug="otro").status_code == 400
    assert _put(client, ev, f, settings={"security": {"enabled": True, "type": "code", "code": ""}}).status_code == 400


def test_field_created_in_form_is_also_created_in_event_parameters_and_vice_versa(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    design = f["design"]
    design["fields"]["talla"] = {"id": "talla", "type": "select", "label": "Talla de camisa", "options": ["S", "M"], "sync": True}
    design["rows"].append({"items": ["talla"]})
    saved = _put(client, ev, f, design=design).json()
    assert saved["design"]["fields"]["talla"]["key"] == "opcional_1"                       # ida: quedó vinculado
    db.refresh(ev)
    assert ev.get_optional_labels() == {"opcional_1": "Talla de camisa"}
    palette = {x["key"]: x for x in client.get(f"/api/events/{ev.id}/form-event-fields").json()}
    assert palette["opcional_1"]["label"] == "Talla de camisa" and "first_name" in palette
    client.post(f"/api/events/{ev.id}/optional-fields", json={"label": "Alergias"})         # vuelta: nace en Parámetros...
    labels = [x["label"] for x in client.get(f"/api/events/{ev.id}/form-event-fields").json()]
    assert "Alergias" in labels                                                             # ...y aparece disponible para el formulario


def test_templates_library_save_and_start_from_one(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    tpl = client.post(f"/api/events/{ev.id}/forms/{f['id']}/save-as-template", json={"name": "Base feria"}).json()
    assert [t["name"] for t in client.get(f"/api/events/{ev.id}/form-templates").json()] == ["Base feria"]
    made = client.post(f"/api/events/{ev.id}/forms", json={"name": "Desde plantilla", "template_id": tpl["id"]}).json()
    assert len(made["design"]["fields"]) == len(f["design"]["fields"])
    other = factory.event("en_proceso", tenant_id="otro")
    assert client.post(f"/api/events/{other.id}/forms", json={"name": "x", "template_id": tpl["id"]}).status_code == 404     # las plantillas son del cliente
    assert client.delete(f"/api/events/{ev.id}/form-templates/{tpl['id']}").status_code == 200


def test_only_coordinador_plus_manage_forms(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    client.post("/logout")
    dig = factory.staff("digitador", "9990001")
    factory.authorize(ev, dig)
    login(client, "9990001")
    assert client.get(f"/api/events/{ev.id}/forms").status_code == 403
    assert client.post(f"/api/events/{ev.id}/forms", json={"name": "x"}).status_code == 403
    assert client.get(f"/kiosk/{ev.id}/formularios").status_code in (302, 403)


# ------------------------------- estados y URL -------------------------------
def test_four_states_and_their_public_behaviour(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    key = f["test_key"]
    client.post("/logout")
    assert client.get(_url(ev, f)).status_code == 404                                       # pruebas sin clave: no existe
    assert client.get(_url(ev, f), params={"k": "mala"}).status_code == 404
    assert client.get(_url(ev, f), params={"k": key}).status_code == 200                     # pruebas con el enlace de pruebas
    assert _state(client, ev, f, k=key)["stage"] == "form" and _state(client, ev, f, k=key)["is_test"] is True

    login(client, "coord1")
    _status(client, ev, f, manual_status="activo")
    client.post("/logout")
    assert client.get(_url(ev, f)).status_code == 200
    st = _state(client, ev, f)
    assert st["stage"] == "form" and st["is_test"] is False and st["design"]["fields"]

    login(client, "coord1")
    _put(client, ev, f, settings={"closed_template": {"title": "Ya cerró", "text": "Vuelve pronto"}})
    _status(client, ev, f, manual_status="cerrado")
    client.post("/logout")
    closed = _state(client, ev, f)
    assert closed["stage"] == "closed" and closed["reason"] == "cerrado" and closed["template"]["title"] == "Ya cerró" and "design" not in closed
    assert client.get(_url(ev, f)).status_code == 200                                       # la URL sigue viva con su plantilla

    login(client, "coord1")
    _status(client, ev, f, manual_status="finalizado")
    client.post("/logout")
    assert client.get(_url(ev, f)).status_code == 404 and client.get(f"{_url(ev, f)}/state").status_code == 404   # ya no existe


def test_schedule_drives_the_state_and_outside_ranges_it_is_closed(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    now = datetime.utcnow() - timedelta(hours=5)                                            # hora local (UTC-5)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M")
    sched = [{"status": "activo", "from": fmt(now - timedelta(hours=1)), "to": fmt(now + timedelta(hours=1))}]
    assert _status(client, ev, f, schedule=sched, use_schedule=True).json()["status"] == "activo"
    past = [{"status": "activo", "from": fmt(now - timedelta(days=3)), "to": fmt(now - timedelta(days=2))}]
    r = _status(client, ev, f, schedule=past).json()
    assert r["status"] == "cerrado" and r["manual_status"] == "pruebas"                     # fuera de todo rango: cerrado por defecto
    assert _status(client, ev, f, use_schedule=False).json()["status"] == "pruebas"         # sin calendario, vale el manual
    assert _status(client, ev, f, schedule=[{"status": "activo", "from": "2026-10-05T00:00", "to": "2026-10-01T00:00"}]).status_code == 400
    f2 = _create(client, ev, "Sin tramos")
    assert _status(client, ev, f2, use_schedule=True).status_code == 400


# ------------------------------- envío, cupo y duplicados -------------------------------
def test_submission_saved_and_test_ones_are_marked(client, factory, db):
    from app.models import FormSubmission

    ev = _event(client, factory)
    f = _create(client, ev)
    key = f["test_key"]
    client.post("/logout")
    r = _submit(client, ev, f, _person_values(), key=key)                                   # en pruebas
    assert r.status_code == 200 and r.json()["is_test"] is True
    login(client, "coord1")
    assert client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["submissions"] == 0     # las de prueba no cuentan como reales
    _status(client, ev, f, manual_status="activo")
    client.post("/logout")
    assert _submit(client, ev, f, _person_values()).json()["is_test"] is False
    assert db.query(FormSubmission).filter_by(is_test=True).count() == 1 and db.query(FormSubmission).filter_by(is_test=False).count() == 1


def test_server_validates_required_fields_types_and_emails(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    r = _submit(client, ev, f, {"cedula": "1", "correo": "x@dominio-falso.com"})
    assert r.status_code == 422 and set(r.json()["errors"]) == {"nombres", "apellidos", "correo"}
    assert "dominio" in r.json()["errors"]["correo"]


def test_capacity_closes_the_form_and_can_be_raised_live_without_losing_submissions(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _status(client, ev, f, manual_status="activo", capacity=2)
    client.post("/logout")
    for i in (1, 2):
        assert _submit(client, ev, f, {**_person_values(), "cedula": f"100{i}"}).status_code == 200
    third = _submit(client, ev, f, {**_person_values(), "cedula": "1003"})
    assert third.status_code == 409 and third.json()["stage"] == "closed"
    st = _state(client, ev, f)
    assert st["stage"] == "closed" and st["reason"] == "cupo_lleno"                          # se distingue del cierre manual/por fecha
    login(client, "coord1")
    assert _status(client, ev, f, capacity=3).json()["public_state"] == "activo"             # subir el cupo en caliente reabre
    assert client.get(f"/api/events/{ev.id}/forms/{f['id']}").json()["submissions"] == 2     # sin perder las ya recibidas
    client.post("/logout")
    assert _submit(client, ev, f, {**_person_values(), "cedula": "1003"}).status_code == 200


def test_duplicate_document_number_is_rejected_but_not_in_tests(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    assert _submit(client, ev, f, _person_values()).status_code == 200
    dup = _submit(client, ev, f, _person_values())
    assert dup.status_code == 409 and dup.json()["duplicate"] is True


# ------------------------------- reglas condicionales (servidor) -------------------------------
def test_conditional_fields_are_enforced_by_the_server(client, factory, db):
    from app.models import FormSubmission

    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [
        {"id": "doc", "type": "select", "label": "Tipo de documento", "options": ["Cédula", "Pasaporte"], "required": True},
        {"id": "vuelo", "type": "text_short", "label": "Número de vuelo", "required": True, "show_if": {"field": "doc", "op": "equals", "value": "Pasaporte"}},
    ]
    _open(client, ev, f, design=_design(fields))
    base = {"cedula": "1001", "nombres": "A", "apellidos": "B"}
    ok = _submit(client, ev, f, {**base, "doc": "Cédula", "vuelo": "AV999 (oculto)"})
    assert ok.status_code == 200
    assert "vuelo" not in json.loads(db.query(FormSubmission).one().data_json)              # lo oculto no se guarda aunque llegue
    need = _submit(client, ev, f, {**base, "cedula": "1002", "doc": "Pasaporte"})
    assert need.status_code == 422 and "vuelo" in need.json()["errors"]
    assert _submit(client, ev, f, {**base, "cedula": "1002", "doc": "Pasaporte", "vuelo": "AV1"}).status_code == 200


# ------------------------------- seguridad -------------------------------
def test_access_code_gate(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"security": {"enabled": True, "type": "code", "code": "Feria26"}})
    _open(client, ev, f)
    assert _state(client, ev, f) == {**_state(client, ev, f), "stage": "gate", "kind": "code"} and "design" not in _state(client, ev, f)
    assert client.post(f"{_url(ev, f)}/gate", json={"code": "mal"}).status_code == 403
    tok = client.post(f"{_url(ev, f)}/gate", json={"code": "feria26"}).json()["token"]           # sin importar mayúsculas
    assert _state(client, ev, f, t=tok)["stage"] == "form"
    assert _submit(client, ev, f, _person_values()).status_code == 403                            # sin pasar por el código, no se puede enviar
    assert _submit(client, ev, f, _person_values(), token=tok).status_code == 200


def test_access_code_attempts_are_rate_limited(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"security": {"enabled": True, "type": "code", "code": "secreto"}})
    _open(client, ev, f)
    codes = [client.post(f"{_url(ev, f)}/gate", json={"code": f"x{i}"}).status_code for i in range(17)]
    assert 429 in codes and codes[0] == 403


def test_own_document_number_as_password(client, factory):
    ev = _event(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    f = _create(client, ev)
    _put(client, ev, f, settings={"security": {"enabled": True, "type": "cedula"}, "prefill": {"mode": "cedula", "source": "event"}})
    _open(client, ev, f)
    assert _state(client, ev, f)["stage"] == "identify" and _state(client, ev, f)["required"] is True
    tok = _state(client, ev, f)["token"]
    assert client.post(f"{_url(ev, f)}/lookup", json={"id": "9999", "t": tok}).status_code == 403      # no está en la base: no entra
    ok = client.post(f"{_url(ev, f)}/lookup", json={"id": "1.001", "t": tok}).json()
    assert ok["found"] is True
    assert _state(client, ev, f, t=ok["token"])["stage"] == "form"


# ------------------------------- pre-llenado -------------------------------
def test_self_service_prefill_locks_visibility_fields_and_ignores_tampering(client, factory, db):
    from app.models import FormSubmission

    ev = _event(client, factory)
    u = factory.person(ev, "1001", "Ana", "Mora")
    u.email = "ana@empresa.com"
    db.commit()
    f = _create(client, ev)
    design = f["design"]
    for fld in design["fields"].values():
        fld["readonly_when_prefilled"] = fld["key"] in ("first_name", "last_name", "email")
    _put(client, ev, f, design=design, settings={"prefill": {"mode": "cedula", "source": "event"}})
    _open(client, ev, f)
    tok = _state(client, ev, f)["token"]
    found = client.post(f"{_url(ev, f)}/lookup", json={"id": "1001", "t": tok}).json()
    st = _state(client, ev, f, t=found["token"])
    pre = {st["design"]["fields"][fid]["key"]: v for fid, v in st["prefill"].items()}
    assert pre["first_name"] == "Ana" and pre["email"] == "ana@empresa.com" and len(st["readonly"]) == 3
    ids = {v["key"]: k for k, v in st["design"]["fields"].items()}
    tampered = {ids["id"]: "1001", ids["first_name"]: "HACKER", ids["last_name"]: "X", ids["email"]: "otro@example.com"}
    assert _submit(client, ev, f, tampered, token=found["token"]).status_code == 200
    saved = json.loads(db.query(FormSubmission).one().data_json)
    assert saved[ids["first_name"]] == "Ana" and saved[ids["email"]] == "ana@empresa.com"        # manda la base, no el navegador
    # una cédula que no existe: el formulario se llena de cero, nada bloqueado
    nf = client.post(f"{_url(ev, f)}/lookup", json={"id": "5555", "t": tok}).json()
    assert nf["found"] is False
    st2 = _state(client, ev, f, t=nf["token"])
    assert st2["stage"] == "form" and st2["prefill"] == {} and st2["readonly"] == []


def test_prefill_from_another_event_of_the_same_client_and_from_an_uploaded_base(client, factory, db):
    ev = _event(client, factory)
    old = factory.event("finalizado")
    factory.person(old, "2002", "Beto", "Viejo")
    f = _create(client, ev)
    _put(client, ev, f, settings={"prefill": {"mode": "cedula", "source": f"event:{old.id}"}})
    _open(client, ev, f)
    tok = _state(client, ev, f)["token"]
    assert client.post(f"{_url(ev, f)}/lookup", json={"id": "2002", "t": tok}).json()["found"] is True
    login(client, "coord1")
    csv = "cedula,nombres,apellidos,correo\n3003,Carla,Subida,carla@example.com\n"
    up = client.post(f"/api/events/{ev.id}/forms/{f['id']}/people", files={"file": ("base.csv", csv.encode(), "text/csv")})
    assert up.status_code == 200 and up.json()["people"] == 1
    client.post("/logout")
    tok = _state(client, ev, f)["token"]
    assert client.post(f"{_url(ev, f)}/lookup", json={"id": "3003", "t": tok}).json()["found"] is True
    assert client.post(f"{_url(ev, f)}/lookup", json={"id": "2002", "t": tok}).json()["found"] is False    # ya no lee el evento anterior


def test_personal_invite_links(client, factory, db, outbox):
    from app.models import FormInvite

    ev = _event(client, factory)
    u = factory.person(ev, "1001", "Ana", "Mora")
    u.email = "ana@example.com"
    factory.person(ev, "1002", "Beto", "SinCorreo")
    db.commit()
    f = _create(client, ev)
    assert client.post(f"/api/events/{ev.id}/forms/{f['id']}/invites/send", json={}).status_code == 400      # el modo no es «invitado»
    _put(client, ev, f, settings={"prefill": {"mode": "invite", "source": "event"}})
    _status(client, ev, f, manual_status="activo")
    monkey_job = client.post(f"/api/events/{ev.id}/forms/{f['id']}/invites/send", json={})
    assert monkey_job.status_code == 200
    import time
    for _ in range(50):
        st = client.get(f"/api/bulk_jobs/{monkey_job.json()['job_id']}").json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.2)
    assert st["status"] == "done" and st["result"]["sent"] == 1 and st["result"]["skipped"] == 1
    assert outbox[0]["to"] == "ana@example.com" and "?i=" in outbox[0]["body"]
    token = outbox[0]["body"].split("?i=")[1].split()[0]
    client.post("/logout")
    assert _state(client, ev, f)["stage"] == "invalid"                                           # sin enlace personal
    assert _state(client, ev, f, i="inventado")["stage"] == "invalid"
    st = _state(client, ev, f, i=token)
    assert st["stage"] == "form" and "1001" in st["prefill"].values()
    ids = {v["key"]: k for k, v in st["design"]["fields"].items()}
    assert _submit(client, ev, f, {ids["id"]: "1001", ids["first_name"]: "Ana", ids["last_name"]: "Mora", ids["email"]: "ana@example.com"}, token=st["token"]).status_code == 200
    assert db.query(FormInvite).filter_by(person_id="1001").one().used_at is not None            # el enlace quedó usado
    assert _submit(client, ev, f, _person_values()).status_code == 403                            # sin enlace personal no se envía


# ------------------------------- archivos -------------------------------
def test_file_upload_validation_storage_and_download(client, factory, db):
    from app.models import FormSubmission

    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "cv", "type": "file", "label": "Hoja de vida", "required": True, "accept": ["pdf", "docx"], "max_mb": 1}]
    _open(client, ev, f, design=_design(fields))
    base = {"cedula": "1001", "nombres": "A", "apellidos": "B"}
    miss = _submit(client, ev, f, base)
    assert miss.status_code == 422 and "cv" in miss.json()["errors"]
    fake = _submit(client, ev, f, base, files={"cv": ("cv.pdf", b"esto no es un pdf", "application/pdf")})
    assert fake.status_code == 422 and "no corresponde" in fake.json()["errors"]["cv"]
    exe = _submit(client, ev, f, base, files={"cv": ("virus.exe", b"MZ....", "application/octet-stream")})
    assert exe.status_code == 422 and "formato no permitido" in exe.json()["errors"]["cv"]
    big = _submit(client, ev, f, base, files={"cv": ("cv.pdf", b"%PDF" + b"0" * (1024 * 1024 + 10), "application/pdf")})
    assert big.status_code == 422 and "1 MB" in big.json()["errors"]["cv"]
    ok = _submit(client, ev, f, base, files={"cv": ("../../mi cv.pdf", b"%PDF-1.4 contenido", "application/pdf")})
    assert ok.status_code == 200
    sub = db.query(FormSubmission).one()
    info = json.loads(sub.data_json)["cv"]
    assert info["filename"] == "mi_cv.pdf" and ".." not in info["stored"]                    # el nombre se sanea, no puede salirse de la carpeta
    login(client, "coord1")
    dl = client.get(f"/api/events/{ev.id}/forms/{f['id']}/files/{sub.id}/cv")
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 contenido"


def test_optional_file_can_be_omitted_and_other_types_validated(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "foto", "type": "file", "label": "Foto", "accept": ["png", "jpg"]}]
    _open(client, ev, f, design=_design(fields))
    assert _submit(client, ev, f, {"cedula": "1001", "nombres": "A", "apellidos": "B"}).status_code == 200


# ------------------------------- alimentar la base del evento -------------------------------
def _person_in_base(db, ev, pid):
    from app.models import AccessLog, EventAttendee, User

    user = db.query(User).filter_by(id=pid, tenant_id=ev.tenant_id).first()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=pid).first()
    logs = db.query(AccessLog).filter_by(event_id=ev.id, user_id=pid).count()
    return user, att, logs


def test_feed_realtime_puts_each_submission_in_the_event_base_as_not_registered(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"feed": "realtime"})
    _open(client, ev, f)
    _submit(client, ev, f, _person_values())
    user, att, logs = _person_in_base(db, ev, "1001")
    assert user.first_name == "Ana" and user.email == "ana@example.com" and att is not None and logs == 0      # quedó «No registrado»
    login(client, "coord1")
    people = {u["id"]: u for u in client.get(f"/api/users?event_id={ev.id}").json()}
    assert people["1001"]["status"] == "No registrado"


def test_feed_realtime_ignores_test_submissions(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"feed": "realtime"})
    key = f["test_key"]
    client.post("/logout")
    _submit(client, ev, f, _person_values(), key=key)
    assert _person_in_base(db, ev, "1001")[0] is None


def test_feed_on_close_loads_everything_when_the_form_closes(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    _put(client, ev, f, settings={"feed": "on_close"})
    _status(client, ev, f, manual_status="activo")
    client.post("/logout")
    _submit(client, ev, f, _person_values())
    _submit(client, ev, f, {**_person_values(), "cedula": "1002", "nombres": "Beto"})
    assert _person_in_base(db, ev, "1001")[0] is None                                        # todavía abierto: no se carga
    login(client, "coord1")
    assert _status(client, ev, f, manual_status="cerrado").status_code == 200                # al cerrar: se cargan todas
    assert _person_in_base(db, ev, "1001")[1] is not None and _person_in_base(db, ev, "1002")[0].first_name == "Beto"


def test_feed_manual_does_nothing_until_feed_now(client, factory, db):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    _submit(client, ev, f, _person_values())
    assert _person_in_base(db, ev, "1001")[0] is None
    login(client, "coord1")
    r = client.post(f"/api/events/{ev.id}/forms/{f['id']}/feed-now").json()
    assert r["fed"] == 1 and _person_in_base(db, ev, "1001")[0].first_name == "Ana"
    assert client.post(f"/api/events/{ev.id}/forms/{f['id']}/feed-now").json()["fed"] == 0       # no se duplica


def test_feed_keeps_existing_data_and_extra_fields_go_to_optionals(client, factory, db):
    ev = _event(client, factory)
    old = factory.person(ev, "1001", "Ana", "Vieja")
    old.phone = "3001112222"
    db.commit()
    f = _create(client, ev)
    design = f["design"]
    design["fields"]["talla"] = {"id": "talla", "type": "select", "label": "Talla", "options": ["S", "M"], "sync": True}
    design["rows"].append({"items": ["talla"]})
    saved = _put(client, ev, f, design=design, settings={"feed": "realtime"}).json()
    ids = {v["key"]: k for k, v in saved["design"]["fields"].items() if v.get("key")}
    _open(client, ev, f)
    _submit(client, ev, f, {ids["id"]: "1001", ids["first_name"]: "Ana", ids["last_name"]: "Nueva", ids["email"]: "ana@example.com", ids["opcional_1"]: "M"})
    user, _, _ = _person_in_base(db, ev, "1001")
    assert user.last_name == "Nueva" and user.phone == "3001112222" and user.get_extras() == {"opcional_1": "M"}   # actualiza lo que llega, no borra lo demás


# ------------------------------- reporte, respuestas y analítica de uso -------------------------------
def test_report_excludes_test_submissions_by_default(client, factory, tmp_path):
    import openpyxl

    ev = _event(client, factory)
    f = _create(client, ev)
    key = f["test_key"]
    client.post("/logout")
    _submit(client, ev, f, {**_person_values(), "cedula": "9001"}, key=key)                 # prueba
    login(client, "coord1")
    _status(client, ev, f, manual_status="activo")
    client.post("/logout")
    _submit(client, ev, f, _person_values(), source="instagram")
    login(client, "coord1")

    def rows(**params):
        r = client.get(f"/api/events/{ev.id}/forms/{f['id']}/report", params=params)
        assert r.status_code == 200
        p = tmp_path / "r.xlsx"
        p.write_bytes(r.content)
        data = list(openpyxl.load_workbook(p).active.iter_rows(values_only=True))
        return data[1], data[2:]

    header, body = rows()
    assert header[:3] == ("N°", "Fecha", "Hora") and "Cédula" in header and len(body) == 1 and body[0][header.index("Origen")] == "instagram"
    _, all_rows = rows(include_tests=True)
    assert len(all_rows) == 2
    subs = client.get(f"/api/events/{ev.id}/forms/{f['id']}/submissions").json()
    assert len(subs["rows"]) == 2 and any(r["is_test"] for r in subs["rows"]) and subs["columns"][0]["label"] == "Cédula"
    assert len(client.get(f"/api/events/{ev.id}/forms/{f['id']}/submissions", params={"include_tests": "false"}).json()["rows"]) == 1


def test_beacons_are_recorded_once_per_session(client, factory, db):
    from app.models import FormEvent

    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    for _ in range(3):
        assert client.post(f"{_url(ev, f)}/beacon", json={"sid": "abc", "kind": "view", "source": "tiktok"}).status_code == 200
    client.post(f"{_url(ev, f)}/beacon", json={"sid": "abc", "kind": "start"})
    assert db.query(FormEvent).filter_by(kind="view").count() == 1 and db.query(FormEvent).filter_by(kind="start").count() == 1
    assert client.post(f"{_url(ev, f)}/beacon", json={"sid": "abc", "kind": "otra"}).status_code == 400


def test_deleting_an_event_removes_its_forms_and_files(client, factory, db):
    from app.models import FormSubmission, WebForm

    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    _submit(client, ev, f, _person_values())
    client.post("/logout")
    factory.staff("admin", "root")
    login(client, "root")
    assert client.delete(f"/api/events/{ev.id}").status_code == 200
    assert db.query(WebForm).count() == 0 and db.query(FormSubmission).count() == 0


def test_public_page_exposes_nothing_else_and_needs_no_login(client, factory):
    ev = _event(client, factory)
    f = _create(client, ev)
    _open(client, ev, f)
    assert client.get(_url(ev, f)).status_code == 200
    assert client.get("/api/events").status_code == 401 and client.get(f"/kiosk/{ev.id}").status_code == 302
