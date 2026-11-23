"""«Pide tu cotización» del sitio web: lógica pura y texto de lo cableado (sin base ni FastAPI). Con base: tests/test_quote_request.py."""
import os
import re

import pytest

from app import quote_core as q

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf8").read()


OK = {"nombre": "Ana Pérez", "empresa": "Acme SAS", "tipo": "Congreso", "fecha": "2027-03-15", "ciudad": "Bogotá", "asistentes": 350, "contacto": "ana@acme.test"}


def test_valido_y_limpio():
    clean, errors = q.validate(dict(OK, website=""))
    assert not errors and clean["asistentes"] == 350 and clean["tipo"] == "Congreso"


def test_empresa_y_fecha_son_opcionales_y_asistentes_acepta_texto_numerico():
    clean, errors = q.validate(dict(OK, empresa="", fecha=None, asistentes="1200"))
    assert not errors and clean["asistentes"] == 1200 and clean["fecha"] == ""


@pytest.mark.parametrize("campo,valor", [
    ("nombre", ""), ("nombre", "<b>x</b>"), ("nombre", "x" * 101), ("nombre", "a\x00b"), ("ciudad", "Bo>gotá"), ("ciudad", None),
    ("tipo", "Boda"), ("tipo", ""), ("fecha", "15/03/2027"), ("fecha", "2027-02-30"), ("asistentes", 0), ("asistentes", 1_000_001),
    ("asistentes", True), ("asistentes", "mil"), ("asistentes", 3.5), ("contacto", "no es nada"), ("contacto", "123"), ("contacto", "a@b"),
    ("empresa", "z" * 121), ("contacto", 3001234567),
])
def test_rechaza_con_un_texto_por_campo(campo, valor):
    clean, errors = q.validate(dict(OK, **{campo: valor}))
    assert list(errors) == [campo] and errors[campo] and errors[campo][0].isupper()


def test_celular_y_correo_validos_como_contacto():
    for c in ("3001234567", "+57 300 123 4567", "(601) 555-1234", "ana.perez+x@acme.com.co"):
        assert not q.validate(dict(OK, contacto=c))[1], c


def test_los_limites_de_asistentes_se_aceptan():
    assert not q.validate(dict(OK, asistentes=1))[1] and not q.validate(dict(OK, asistentes=1_000_000))[1]


def test_todos_los_tipos_del_sitio():
    assert q.TIPOS == ("Congreso", "Convención", "Asamblea de accionistas", "Junta directiva", "Lanzamiento", "Feria comercial", "Evento académico", "Otro")
    assert all(not q.validate(dict(OK, tipo=t))[1] for t in q.TIPOS)


def test_cuerpo_que_no_es_objeto():
    assert q.validate([1, 2])[1] and q.validate(None)[1]


def test_correo_reply_to_solo_si_el_contacto_es_correo():
    clean, _ = q.validate(OK)
    m = q.build_mail(clean)
    assert m["subject"] == "Nueva solicitud de cotización · Congreso · Bogotá" and m["reply_to"] == "ana@acme.test"
    for dato in ("Ana Pérez", "Acme SAS", "Congreso", "2027-03-15", "Bogotá", "350", "ana@acme.test"):
        assert dato in m["text"]
    clean, _ = q.validate(dict(OK, contacto="3001234567"))
    assert q.build_mail(clean)["reply_to"] is None


def test_origenes_permitidos():
    raw = "https://golden-eventos.com, https://www.golden-eventos.com/ ,*"
    assert q.allowed_origins(raw) == ["https://golden-eventos.com", "https://www.golden-eventos.com"]
    assert q.origin_allowed("https://golden-eventos.com", raw) and not q.origin_allowed("https://malo.test", raw)
    assert not q.origin_allowed("https://golden-eventos.com", "") and not q.origin_allowed(None, raw)
    h = q.cors_headers("https://www.golden-eventos.com", raw)
    assert h["Access-Control-Allow-Origin"] == "https://www.golden-eventos.com" and "*" not in h.values() and "Access-Control-Allow-Credentials" not in h
    assert q.cors_headers("https://malo.test", raw) == {}


def test_por_defecto_sin_variable_no_se_permite_ningun_origen(monkeypatch):
    monkeypatch.delenv("QUOTE_ALLOWED_ORIGINS", raising=False)
    assert q.allowed_origins() == [] and not q.origin_allowed("https://golden-eventos.com")


# ------------------------------- texto de lo cableado -------------------------------
def test_la_ruta_es_def_y_esta_cableada():
    router = _read("app/routers/quote_request.py")
    assert "async def" not in router and "def quote_request(" in router and '@router.post("/api/public/quote-request")' in router and '@router.options("/api/public/quote-request")' in router
    assert "website" in router and "QUOTE_TO_EMAIL sin configurar" in router and "Depends(get_current" not in router
    assert "quote_request_router.router" in _read("app/main.py")
    assert q.PATH == "/api/public/quote-request" and '"/api/public/"' in _read("app/appmode.py")


def test_el_csrf_solo_exceptua_esta_ruta():
    main = _read("app/main.py")
    m = re.search(r"request\.url\.path == quote_core\.PATH and quote_core\.origin_allowed\(origin\)", main)
    assert m and main.count("quote_core.origin_allowed") == 1


def test_tope_de_cuerpo_de_8kb():
    assert q.MAX_BODY_BYTES == 8192 and 'path == "/api/public/quote-request"' in _read("app/bodylimit.py") and "return 8 * KB" in _read("app/bodylimit.py")


def test_el_tipo_de_trabajo_esta_registrado_y_el_manejador_no_guarda_datos_personales():
    jobs = _read("app/jobs.py")
    assert jobs.count('"quote_mail"') == 3 or ('"quote_mail"})' in jobs and '"quote_mail": "app.quote_mail"' in jobs)
    mail = _read("app/quote_mail.py")
    assert "@jobs.handler(MAIL_KIND)" in mail and 'os.getenv("QUOTE_TO_EMAIL")' in mail and "log.info" not in mail


def test_ni_correo_ni_secreto_en_el_repo():
    for rel in ("app/quote_core.py", "app/quote_mail.py", "app/routers/quote_request.py", ".env.example", ".env.staging.example"):
        s = _read(rel)
        assert not re.search(r"QUOTE_TO_EMAIL=\S", s), rel
    for rel in ("app/quote_core.py", "app/quote_mail.py", "app/routers/quote_request.py"):
        assert not re.search(r"[\w.]+@(?!acme)[\w.]+\.\w+", _read(rel).replace("ana@acme.test", "")), rel
    assert "# QUOTE_TO_EMAIL=" in _read(".env.example") and "# QUOTE_ALLOWED_ORIGINS=" in _read(".env.staging.example")


def test_readme_de_despliegue_documenta_las_variables():
    r = _read("deploy/gcp/README.md")
    assert "QUOTE_TO_EMAIL" in r and "Secret Manager" in r and "QUOTE_ALLOWED_ORIGINS" in r
