"""Escenario «sin biometría»: con el rostro apagado no aparece nada de biometría, y con el candado el SERVIDOR rechaza fotos y no deja encender el rostro (ni por el zip de la carga)."""
import io
import json
import re
import zipfile
from datetime import date

import pytest
from PIL import Image

from app.models import User
from tests.conftest import login


@pytest.fixture(autouse=True)
def company_env(monkeypatch):
    for k, v in {"COMPANY_NAME": "Golden Eventos y Logística S.A.S.", "COMPANY_NIT": "901542833-2", "PRIVACY_EMAIL": "soporteit@goldenlogisticas.com", "DOMAIN": "golden-eventos.com"}.items():
        monkeypatch.setenv(k, v)


def _photo():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 100, 50)).save(buf, "JPEG")
    return buf.getvalue()


def _zip(*ids):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for uid in ids:
            z.writestr(f"{uid}.jpg", _photo())
    return buf.getvalue()


def _coord(client, factory, status="creado", **extra):
    factory.staff("coordinador", "coord1")
    ev = factory.event(status, **extra)
    login(client, "coord1")
    return ev


def _bulk(client, ev, csv, zip_bytes=None):
    files = {"roster_file": ("b.csv", csv.encode(), "text/csv")}
    data = {"event_id": str(ev.id)}
    if zip_bytes:
        files["zip_file"] = ("f.zip", zip_bytes, "application/zip")
        data["photos_authorized"] = "true"
    return client.post("/api/bulk_register", data=data, files=files)


# ------------------------------------------------------------------------------------------------------------------------------- lo que ve la puerta sin rostro
def test_the_registration_page_has_no_biometric_screen_nor_birth_date_field_without_the_face(client, factory):
    ev = _coord(client, factory, "en_proceso")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert 'id="bioIdent"' not in page and 'id="video"' not in page and 'id="regPhotoInput"' not in page and 'name="biometric_consent"' not in page and 'name="birth_date"' not in page
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S))          # solo lo que ve la persona: sin código ni estilos
    assert not re.search(r"(?i)biom|rostro|facial|selfie|menor de|reconocimiento", visible), re.findall(r"(?i).{0,40}(?:biom|rostro|facial|selfie|menor de|reconocimiento).{0,40}", visible)
    on = factory.event("en_proceso", facial_enabled=True)
    assert 'name="birth_date"' in client.get(f"/kiosk/{on.id}/registro").text                          # con rostro, sí


def test_birth_date_is_not_a_parameter_nor_an_edit_field_nor_a_directory_value_without_the_face(client, factory, db):
    ev = _coord(client, factory, "en_proceso")
    u = factory.person(ev, "1001")
    u.birth_date = date(1990, 1, 1)
    db.commit()
    assert "birth_date" not in {c["key"] for c in client.get(f"/api/events/{ev.id}/field-configs").json()}
    row = next(r for r in client.get(f"/api/users?event_id={ev.id}").json() if r["id"] == "1001")
    assert row["birth_date"] == ""                                                                      # no se entrega
    assert client.patch(f"/api/users/1001?event_id={ev.id}", json={"birth_date": "2000-02-02", "first_name": "Ana"}).status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().birth_date == date(1990, 1, 1)                     # se ignoró: no se toca
    on = factory.event("en_proceso", facial_enabled=True)
    assert "birth_date" in {c["key"] for c in client.get(f"/api/events/{on.id}/field-configs").json()}


def test_the_local_roster_without_the_face_carries_no_consent_flags_and_does_no_consent_queries(client, factory, db, monkeypatch):
    ev = _coord(client, factory, "en_proceso")
    u = factory.person(ev, "1001")
    u.birth_date = date(date.today().year - 10, 1, 1)
    db.commit()
    from app import consent
    monkeypatch.setattr(consent, "accepted_user_ids", lambda *a, **k: (_ for _ in ()).throw(AssertionError("consulta de consentimiento sin rostro")))
    body = client.get(f"/api/events/{ev.id}/local-roster").json()
    assert body["consent"] is None and body["people"][0]["a"] == 0 and body["people"][0]["b"] == 0 and body["people"][0]["v"] == 0


# ------------------------------------------------------------------------------------------------------------------------------- resumen del paso guiado
def test_the_summary_says_ready_without_biometrics_and_the_lock_is_explained(client, factory, db):
    ev = _coord(client, factory, "en_proceso")
    s = client.get(f"/api/events/{ev.id}/biometric-setup").json()
    assert s["ready"] is True and s["missing"] == [] and s["headline"] == "✅ Listo: este evento no usa biometría"
    text = " ".join(s["door"])
    assert "cédula o QR" in text and "no se calcula ni se guarda ninguna foto ni vector" in text and "marca «Este evento NO usa biometría»" in text
    assert client.put(f"/api/events/{ev.id}/biometric-setup", json={"biometrics_locked": True}).status_code == 200
    s = client.get(f"/api/events/{ev.id}/biometric-setup").json()
    assert s["config"]["biometrics_locked"] is True and "BLOQUEADO sin biometría" in " ".join(s["door"])
    assert "Paso 0" in client.get(f"/kiosk/{ev.id}/parametros").text and 'id="bsLocked"' in client.get(f"/kiosk/{ev.id}/parametros").text


# ------------------------------------------------------------------------------------------------------------------------------- candado
def test_locking_turns_everything_biometric_off_and_nothing_can_turn_it_back_on(client, factory, db):
    ev = _coord(client, factory, "en_proceso", facial_enabled=True, aceptar_enabled=True, client_photos_before=True)
    r = client.put(f"/api/events/{ev.id}/biometric-setup", json={"biometrics_locked": True})
    assert r.status_code == 200
    c = r.json()["config"]
    assert c["biometrics_locked"] is True and c["facial_enabled"] is False and c["aceptar_enabled"] is False and c["client_photos_before"] is False
    bad = client.put(f"/api/events/{ev.id}/biometric-setup", json={"facial_enabled": True})
    assert bad.status_code == 400 and "SIN biometría" in bad.json()["detail"]
    assert client.put(f"/api/events/{ev.id}/biometric-setup", json={"biometrics_locked": True, "facial_enabled": True}).status_code == 400          # pedirlo junto tampoco
    toggle = client.put(f"/api/events/{ev.id}/facial-enabled", json={"enabled": True})
    assert toggle.status_code == 409 and "bloqueado" in toggle.json()["detail"]
    db.refresh(ev)
    assert ev.facial_enabled is False and ev.biometrics_locked is True
    assert client.put(f"/api/events/{ev.id}/biometric-setup", json={"biometrics_locked": False}).status_code == 200            # quitar el bloqueo es explícito
    assert client.put(f"/api/events/{ev.id}/biometric-setup", json={"facial_enabled": True}).status_code == 200


def test_a_locked_event_refuses_photos_in_manual_registration_and_registers_without_one(client, factory, db):
    ev = _coord(client, factory, "en_proceso", biometrics_locked=True)
    data = {"event_id": ev.id, "id": "1001", "first_name": "Ana", "last_name": "Mora", "biometric_consent": "true", "birth_date": "1990-01-01"}
    r = client.post("/api/register", data=data, files={"file": ("f.jpg", _photo(), "image/jpeg")})
    assert r.status_code == 400 and "no usa biometría" in r.json()["detail"] and db.query(User).filter_by(id="1001").first() is None
    ok = client.post("/api/register", data={"event_id": ev.id, "id": "1001", "first_name": "Ana", "last_name": "Mora"})
    assert ok.status_code == 200 and db.query(User).filter_by(id="1001").one().face_encoding is None


def test_a_zip_on_a_locked_event_is_ignored_with_a_notice_and_never_turns_the_face_on(client, factory, db):
    from app.storage import get_storage, photo_key
    ev = _coord(client, factory, biometrics_locked=True)
    r = _bulk(client, ev, "id,nombres,apellidos\n1001,Ana,Mora\n", _zip("1001"))
    assert r.status_code == 200 and r.json()["count"] == 1, r.text
    assert any("no usa biometría" in e and "zip" in e for e in r.json()["errors"])
    db.refresh(ev)
    assert ev.facial_enabled is False and not get_storage().exists(photo_key(ev.tenant_id, "1001"))
    assert db.query(User).filter_by(id="1001").one().face_captured_at is None


def test_the_birth_date_column_is_ignored_with_a_notice_in_an_event_without_the_face(client, factory, db):
    ev = _coord(client, factory)
    r = _bulk(client, ev, "id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,2011-03-10\n1002,Beto,Paz,no-es-fecha\n")
    assert r.status_code == 200 and r.json()["count"] == 2
    cols = r.json()["columns"]
    assert {"title": "fecha de nacimiento", "reason": "no se usa en este evento (no tiene reconocimiento facial)"} in cols["unused"]
    assert not any("Fecha de nacimiento" == c["field"] for c in cols["recognized"])       # ni siquiera se valida cada fecha...
    assert r.json()["birth"]["ignored_rows"] == 2 and r.json()["errors"][0].startswith("⚠️ 2 fila(s) traían fecha de nacimiento y NO se guardaron") and len(r.json()["errors"]) == 1      # ...pero SÍ se avisa, una sola vez
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().birth_date is None
    on = factory.event("creado", facial_enabled=True)
    r2 = _bulk(client, on, "id,nombres,apellidos,fecha de nacimiento\n2001,Cata,Menor,2011-03-10\n")
    assert r2.status_code == 200
    db.expire_all()
    assert db.query(User).filter_by(id="2001").one().birth_date == date(2011, 3, 10)                     # con rostro, se guarda


def test_a_zip_never_turns_the_face_on_the_choice_lives_only_in_parameters(client, factory, db):
    ev = _coord(client, factory)
    r = _bulk(client, ev, "id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,1990-04-02\n", _zip("1001"))
    assert r.status_code == 400 and "origen A" in r.json()["detail"]                                        # Fase 0: una sola fuente de verdad (el paso guiado)
    db.refresh(ev)
    assert ev.facial_enabled is False
    ev.facial_enabled, ev.client_photos_before = True, True                                                  # elegido en Parámetros: ahora sí
    db.commit()
    r = _bulk(client, ev, "id,nombres,apellidos,fecha de nacimiento\n1001,Ana,Mora,1990-04-02\n", _zip("1001"))
    assert r.status_code == 200 and db.query(User).filter_by(id="1001").one().birth_date == date(1990, 4, 2)


def test_a_birth_date_column_never_deletes_a_photo_that_belongs_to_another_event(client, factory, db):
    """Sin rostro la fecha se ignora y NO se toca ninguna foto guardada de la persona en otro evento."""
    from app.storage import get_storage, photo_key
    ev = _coord(client, factory)
    get_storage().put(photo_key(ev.tenant_id, "1001"), b"foto-de-otro-evento")
    r = _bulk(client, ev, "id,nombres,apellidos\n1001,Ana,Mora\n")
    assert r.status_code == 200 and get_storage().exists(photo_key(ev.tenant_id, "1001"))
    assert not [e for e in r.json()["errors"] if "fecha de nacimiento" in e]


def test_the_migration_adds_the_lock_column_off_by_default(db):
    from sqlalchemy import text
    row = db.execute(text("SELECT column_default, is_nullable FROM information_schema.columns WHERE table_name = 'events' AND column_name = 'biometrics_locked'")).one()
    assert "false" in row[0] and row[1] == "NO"
    assert json.dumps(True)
