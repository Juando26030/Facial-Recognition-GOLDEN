"""«Pide tu cotización» (POST /api/public/quote-request) con base: honeypot, validación, 503, correo encolado, límite por IP y orígenes. Puras: tests/test_quote_request_puro.py."""
import json

import pytest

from app import jobs
from app.models import Job

URL = "/api/public/quote-request"
OK = {"nombre": "Ana Pérez", "empresa": "Acme SAS", "tipo": "Congreso", "fecha": "2027-03-15", "ciudad": "Bogotá", "asistentes": 350, "contacto": "ana@acme.test", "website": ""}
SITE = "https://golden-eventos.com"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from app import quote_mail  # noqa: F401  (registra el manejador del correo)
    from app.routers import quote_request
    quote_request._limiter._hits.clear()
    monkeypatch.setenv("QUOTE_TO_EMAIL", "destino@golden.test")
    monkeypatch.setenv("QUOTE_ALLOWED_ORIGINS", f"{SITE},https://www.golden-eventos.com")
    monkeypatch.setattr(jobs, "kick", lambda *a, **k: None)          # el correo se ejecuta a mano para ver lo que se enviaría


@pytest.fixture()
def sent(monkeypatch):
    out = []
    from app import mailer
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body, **k: out.append({"to": to, "subject": subject, "body": body, **k}) or {"sent": True, "detail": "ok"})
    return out


def _quote_jobs(db):
    return db.query(Job).filter(Job.kind == "quote_mail").all()


def test_honeypot_responde_200_y_no_hace_nada(client, db):
    r = client.post(URL, json=dict(OK, website="http://spam.test"))
    assert r.status_code == 200 and r.json() == {"ok": True} and not _quote_jobs(db)


def test_envio_valido_encola_un_correo_al_destinatario_configurado(client, db, sent):
    r = client.post(URL, json=OK)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(_quote_jobs(db)) == 1
    assert jobs.run_once(kinds={"quote_mail"}) == 1
    assert len(sent) == 1 and sent[0]["to"] == "destino@golden.test" and sent[0]["reply_to"] == "ana@acme.test"
    assert sent[0]["subject"] == "Nueva solicitud de cotización · Congreso · Bogotá"
    assert all(d in sent[0]["body"] for d in ("Ana Pérez", "Acme SAS", "2027-03-15", "350", "ana@acme.test"))


def test_con_celular_no_hay_reply_to(client, db, sent):
    assert client.post(URL, json=dict(OK, contacto="3001234567")).status_code == 200
    jobs.run_once(kinds={"quote_mail"})
    assert sent[0]["reply_to"] is None


def test_validacion_400_en_espanol_por_campo(client, db):
    r = client.post(URL, json=dict(OK, nombre="<b>x</b>", asistentes=0, tipo="Boda", fecha="mañana"))
    assert r.status_code == 400
    errors = r.json()["errors"]
    assert set(errors) == {"nombre", "asistentes", "tipo", "fecha"} and all(isinstance(v, str) and v for v in errors.values())
    assert not _quote_jobs(db)


def test_sin_destinatario_configurado_responde_503_y_no_encola(client, db, monkeypatch, caplog):
    monkeypatch.delenv("QUOTE_TO_EMAIL")
    r = client.post(URL, json=OK)
    assert r.status_code == 503 and r.json()["detail"] == "No se pudo enviar ahora, escríbanos por WhatsApp"
    assert "QUOTE_TO_EMAIL sin configurar" in caplog.text and "ana@acme.test" not in caplog.text and "Ana" not in caplog.text
    assert not _quote_jobs(db)


def test_el_trabajo_terminado_ya_no_guarda_los_datos_del_visitante(client, db, sent):
    client.post(URL, json=OK)
    jobs.run_once(kinds={"quote_mail"})
    db.expire_all()
    j = _quote_jobs(db)[0]
    assert "ana@acme.test" not in (j.payload_json or "")


def test_limite_de_intentos_por_ip(client, db, monkeypatch):
    monkeypatch.setenv("QUOTE_IP_MAX_PER_10MIN", "2")
    assert [client.post(URL, json=OK).status_code for _ in range(3)] == [200, 200, 429]
    assert len(_quote_jobs(db)) == 2


def test_origen_permitido_pasa_y_recibe_cabeceras_cors(client, db):
    r = client.post(URL, json=OK, headers={"Origin": SITE})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == SITE and "access-control-allow-credentials" not in r.headers


def test_origen_no_permitido_se_rechaza(client, db):
    r = client.post(URL, json=OK, headers={"Origin": "https://malo.test"})
    assert r.status_code == 403 and not _quote_jobs(db)


def test_sin_variable_de_origenes_solo_mismo_origen(client, db, monkeypatch):
    monkeypatch.delenv("QUOTE_ALLOWED_ORIGINS")
    assert client.post(URL, json=OK, headers={"Origin": SITE}).status_code == 403
    assert client.post(URL, json=OK, headers={"Origin": "http://testserver"}).status_code == 200


def test_otra_ruta_no_acepta_los_origenes_del_sitio(client):
    r = client.post("/login", data={"username": "x", "password": "y"}, headers={"Origin": SITE})
    assert r.status_code == 403


def test_preflight(client):
    r = client.options(URL, headers={"Origin": SITE, "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == SITE
    assert "POST" in r.headers["access-control-allow-methods"] and "Content-Type" in r.headers["access-control-allow-headers"]
    r = client.options(URL, headers={"Origin": "https://malo.test"})
    assert r.status_code == 403 and "access-control-allow-origin" not in r.headers


def test_cuerpo_mayor_a_8kb_da_413(client):
    r = client.post(URL, content=json.dumps(dict(OK, nombre="x" * 9000)), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
