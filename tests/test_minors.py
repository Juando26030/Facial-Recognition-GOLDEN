"""L3: menores de 18 años. Sin cámara, sin pantalla de autorización, sin vector y con `is_biometric_enabled=false`; solo cédula/QR."""
import io
import json
import uuid
import re
from datetime import date, datetime

import numpy as np
import pytest
from PIL import Image

from app import consent, faces, legal_texts, ops_runner
from app.models import EventAttendee, User
from tests.conftest import login


def _photo():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


def _years_ago(n, days=0):
    t = date.today()
    return date(t.year - n, t.month, min(t.day, 28)).isoformat() if days == 0 else date.fromordinal(date(t.year - n, t.month, min(t.day, 28)).toordinal() + days).isoformat()


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr("app.routers.api.BiometricEngine.extract_encoding", staticmethod(lambda img, is_registration=False, **kw: [[0.1] * 128]))


def _kiosk(client, factory):
    staff = factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso", facial_enabled=True)
    factory.authorize(ev, staff)
    login(client, "9990001")
    return ev


def _register(client, ev, uid, birth=None, photo=True):
    data = {"event_id": ev.id, "id": uid, "first_name": "Ana", "last_name": "Mora", "biometric_consent": "true"}
    if birth is not None:
        data["birth_date"] = birth
    return client.post("/api/register", data=data, files={"file": ("f.jpg", _photo(), "image/jpeg")} if photo else None)


def test_a_photo_needs_a_birth_date_and_an_adult_keeps_the_face(client, factory, db, engine):
    ev = _kiosk(client, factory)
    r = _register(client, ev, "1001")
    assert r.status_code == 400 and "fecha de nacimiento" in r.json()["detail"] and db.query(User).filter_by(id="1001").first() is None
    assert _register(client, ev, "1001", birth="no-es-fecha").status_code == 400
    ok = _register(client, ev, "1001", birth=_years_ago(30))
    assert ok.status_code == 200 and "minor" not in ok.json()
    u = db.query(User).filter_by(id="1001").one()
    assert u.face_encoding is None and u.face_captured_at and u.is_biometric_enabled is True and u.birth_date is not None      # adulto sin aceptación: foto guardada, SIN vector
    from tests.conftest import accept
    accept(db, ev, "5005")
    assert _register(client, ev, "5005", birth=_years_ago(30)).status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="5005").one().face_encoding                                    # con aceptación de la persona, sí


def test_a_minor_is_registered_without_face_and_blocked(client, factory, db, engine):
    ev = _kiosk(client, factory)
    r = _register(client, ev, "2002", birth=_years_ago(17))
    assert r.status_code == 200 and "menor de 18" in r.json()["minor"]
    u = db.query(User).filter_by(id="2002").one()
    assert u.face_encoding is None and u.is_biometric_enabled is False
    from app.storage import get_storage, photo_key
    assert not get_storage().exists(photo_key(ev.tenant_id, "2002"))                  # ni la foto se guardó
    turns_18_tomorrow = date.fromordinal(date.today().toordinal() + 1)
    birth = date(turns_18_tomorrow.year - 18, turns_18_tomorrow.month, turns_18_tomorrow.day) if not (turns_18_tomorrow.month == 2 and turns_18_tomorrow.day == 29) else date(turns_18_tomorrow.year - 18, 2, 28)
    assert "minor" in _register(client, ev, "4004", birth=birth.isoformat()).json()   # cumple 18 mañana: hoy sigue siendo menor


def test_the_consent_screen_never_applies_to_a_minor_and_the_roster_flags_them(client, factory, db, engine):
    ev = _kiosk(client, factory)
    _register(client, ev, "2002", birth=_years_ago(15))
    st = client.get(f"/api/events/{ev.id}/consent-status/2002").json()
    assert st["blocked"] is True and st["accepted"] is False
    t = legal_texts.render(ev)
    r = client.post(f"/api/events/{ev.id}/consents", json={"entries": [{"id": str(uuid.uuid4()), "user_id": "2002", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"]}]})
    assert r.status_code == 200 and not consent.has_acceptance(db, ev.tenant_id, "2002", ev.id)         # aunque alguien lo envíe, un menor nunca queda como aceptado
    people = {p["n"]: p for p in client.get(f"/api/events/{ev.id}/local-roster").json()["people"]}
    assert people["Ana Mora"]["b"] == 1 and people["Ana Mora"]["a"] == 0


def test_a_minor_with_a_vector_is_never_recognized_even_with_acceptance_or_click(factory, db):
    ev = factory.event("en_proceso", facial_enabled=True, controller_mode="tercero", organizer_name="O", organizer_nit="1", organizer_privacy_email="o@o.test", precalculo_autorizado=True)
    for uid, ok in (("1001", True), ("2002", False)):
        db.add(User(id=uid, tenant_id=ev.tenant_id, first_name=uid, last_name="X", face_encoding=json.dumps(np.random.default_rng(int(uid)).normal(0, 0.1, 128).tolist()), is_biometric_enabled=ok))
        db.flush()
        db.add(EventAttendee(event_id=ev.id, user_id=uid, tenant_id=ev.tenant_id))
    db.commit()
    consent.record(db, tenant_id=ev.tenant_id, user_id="2002", event_id=ev.id, version="v", legal_text_hash="a" * 64, accepted=True, adult=True, reason="consent")
    db.commit()
    faces.clear_cache()
    assert faces.event_index(db, ev, ungated=True).ids == ["1001"] and faces.event_index(db, ev).ids == []


def test_birth_date_from_the_web_form_flags_the_person(db, factory):
    from app import formsvc
    from app.formlib import IDENTITY_KEYS
    assert "birth_date" in IDENTITY_KEYS
    ev = factory.event("en_proceso", facial_enabled=True)
    kv = {"id": "7007", "first_name": "Ana", "birth_date": _years_ago(16)}
    design = {"fields": {}}
    import app.formsvc as fs
    orig_get_design, orig_key_values = fs.get_design, fs.key_values
    fs.get_design, fs.key_values = (lambda form: design), (lambda d, data: kv)
    try:
        sub = type("S", (), {"data_json": "{}", "fed": False, "is_test": True})()
        form = type("F", (), {"event_id": ev.id})()
        assert formsvc.feed_submission(db, form, sub, lambda *a, **k: None) is None
    finally:
        fs.get_design, fs.key_values = orig_get_design, orig_key_values
    db.commit()
    u = db.query(User).filter_by(id="7007").one()
    assert u.birth_date is not None and u.is_biometric_enabled is False


def test_bulk_roster_birth_column_blocks_minors_and_requires_a_date_for_a_face(client, factory, db, engine):
    import zipfile
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, client_photos_before=True)
    login(client, "coord1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for uid in ("1001", "2002", "3003"):
            z.writestr(f"{uid}.jpg", _photo())
    csv = ("id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Adulta,1990-04-02\n2002,Beto,Menor," + _years_ago(14) + "\n3003,Cata,SinFecha,\n").encode()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"}, files={"roster_file": ("b.csv", csv, "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    db.expire_all()
    by = {u.id: u for u in db.query(User).filter(User.id.in_(["1001", "2002", "3003"]))}
    assert by["1001"].face_encoding is None and by["1001"].face_captured_at and by["1001"].is_biometric_enabled is True      # adulto: foto guardada, vector solo tras aceptar
    assert by["2002"].face_encoding is None and by["2002"].is_biometric_enabled is False and by["2002"].birth_date is not None
    assert by["3003"].face_encoding is None                                                  # con foto pero sin fecha de nacimiento: no se conserva el rostro
    from app.storage import get_storage, photo_key
    assert get_storage().exists(photo_key(ev.tenant_id, "1001")) and not get_storage().exists(photo_key(ev.tenant_id, "2002")) and not get_storage().exists(photo_key(ev.tenant_id, "3003"))
    assert any("menor de 18" in str(e) for e in r.json().get("errors", [])) and any("no fecha de nacimiento" in str(e) for e in r.json().get("errors", []))


# La clave del archivo lleva la hora (minors-review/YYYYMMDDTHHMMSS.json): a las 20:02:02 contiene «2002». Se prueba también con esa hora fija.
@pytest.mark.parametrize("now", [None, datetime(2026, 10, 17, 20, 2, 2)])
def test_list_minors_reports_but_deletes_nothing(db, factory, capsys, monkeypatch, now):
    if now:
        monkeypatch.setattr(ops_runner, "utcnow", lambda: now)
    ev = factory.event("en_proceso", facial_enabled=True)
    db.add(User(id="2002", tenant_id=ev.tenant_id, first_name="N", last_name="X", face_encoding="[[0.1]]", birth_date=date.fromisoformat(_years_ago(12)), is_biometric_enabled=True))
    db.add(User(id="3003", tenant_id=ev.tenant_id, first_name="N", last_name="X", face_encoding="[[0.1]]", birth_date=date.fromisoformat(_years_ago(40))))
    db.commit()
    assert ops_runner.main("list-minors") == 0
    out = capsys.readouterr().out
    shown = re.sub(r"minors-review/\S+\.json", "minors-review/<archivo>.json", out)           # el nombre del archivo lleva la hora; lo que importa es que la cédula no salga en el resto
    assert "1 menores con datos biométricos en minors-review/" in out and "2002" not in shown
    assert not now or "T200202" in out                                                      # con la hora fija, «2002» SÍ está en la salida (en el nombre del archivo)
    assert not now or "T200202" in out                                                      # con la hora fija, «2002» SÍ está en la salida (en el nombre del archivo)
    assert db.query(User).filter_by(id="2002").one().face_encoding                     # solo se lista: la decisión de borrar es de una persona


def test_bulk_zip_photos_are_stored_under_the_persons_key_so_the_purge_finds_them(client, factory, db, engine):
    """Regresión: la foto del zip quedaba como «<cédula>.jpg.jpg» y ni se mostraba al operador ni la borraba la purga."""
    import zipfile
    from app.storage import get_storage, photo_key
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, client_photos_before=True)
    login(client, "coord1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1001.jpg", _photo())
    csv = "\n".join(["id,nombres,apellidos,fecha de nacimiento", "1001,Ana,Adulta,1990-04-02", ""]).encode()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"}, files={"roster_file": ("b.csv", csv, "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert get_storage().exists(photo_key(ev.tenant_id, "1001")) and not get_storage().exists(photo_key(ev.tenant_id, "1001.jpg"))
    from app import privacy
    assert privacy.purge_person(db, ev.tenant_id, "1001") is True and not get_storage().exists(photo_key(ev.tenant_id, "1001"))


def test_rule_a_bulk_photo_gets_its_vector_only_after_the_person_accepts_and_photo_only_is_purged(client, factory, db, engine, monkeypatch):
    """REGLA A: la carga masiva guarda la foto cifrada y NO calcula el vector; al aceptar la persona se calcula por tarea; una foto sin vector también se borra a los 7 días."""
    import zipfile
    from datetime import timedelta
    from app import legal_texts, privacy
    from app.storage import get_storage, photo_key
    from app.timeutil import utcnow
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True, client_photos_before=True)
    login(client, "coord1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1001.jpg", _photo())
        z.writestr("2002.jpg", _photo())
    csv = "\n".join(["id,nombres,apellidos,fecha de nacimiento", "1001,Ana,Adulta,1990-04-02", "2002,Eva,Otra,1991-01-01", ""]).encode()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "photos_authorized": "true"}, files={"roster_file": ("b.csv", csv, "text/csv"), "zip_file": ("f.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200 and any("NO se calcula todavía" in str(e) for e in r.json().get("errors", []))
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().face_encoding is None and get_storage().exists(photo_key(ev.tenant_id, "1001"))
    t = legal_texts.render(ev)
    body = {"entries": [{"id": str(uuid.uuid4()), "user_id": "1001", "decision": "accept", "adult": True, "text_hash": t["hash"], "version": t["version"]}]}
    assert client.post(f"/api/events/{ev.id}/consents", json=body).status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().face_encoding and db.query(User).filter_by(id="2002").one().face_encoding is None      # solo quien aceptó
    # foto sin vector (2002 nunca aceptó): el evento finaliza hace 8 días y la purga borra la foto
    ev.status, ev.finalized_at = "finalizado", utcnow() - timedelta(days=8)
    db.commit()
    privacy.purge_expired(db)
    assert not get_storage().exists(photo_key(ev.tenant_id, "2002")) and not get_storage().exists(photo_key(ev.tenant_id, "1001"))
