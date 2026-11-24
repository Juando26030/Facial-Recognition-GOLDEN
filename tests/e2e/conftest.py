"""Base de las pruebas E2E (navegador real contra STAGING). Solo corren con E2E_BASE_URL; sin ella, pytest ni las recoge.

Variables de entorno (nunca valores en el repo): E2E_BASE_URL (obligatoria), E2E_USER / E2E_PASSWORD (cuenta de pruebas de staging),
E2E_DIGITADOR_USER / E2E_DIGITADOR_PASSWORD (opcional), E2E_URL_PUBLICO / E2E_URL_BIOMETRIA (opcionales, para el humo de /health),
E2E_TENANT_ID (opcional: cliente de staging donde crear el evento sintético; por defecto el primero que devuelva la API).
"""
import datetime
import json
import os
import uuid
from urllib.parse import urlencode, urlsplit

import pytest

# Sin E2E_BASE_URL, la suite normal (que no tiene navegador ni staging) ignora todos los test_*.py de esta carpeta.
if not os.environ.get("E2E_BASE_URL"):
    collect_ignore_glob = ["test_*.py"]

# Las pruebas E2E hablan con STAGING por navegador: no necesitan base de datos local ni importar la app. El conftest general de tests/
# trae preparativos automáticos (autouse) que sí los usan (Postgres local, migraciones, dobles del motor facial…); aquí se anulan por
# nombre para que esta carpeta corra en cualquier máquina (p. ej. Cloud Shell) con solo playwright + pytest.
@pytest.fixture(scope="session", autouse=True)
def _database():
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield


@pytest.fixture(autouse=True)
def _server_never_left_locked():
    yield


@pytest.fixture(autouse=True)
def _no_wompi_status_network():
    yield


@pytest.fixture(autouse=True)
def _no_wompi_reference_network():
    yield


@pytest.fixture(autouse=True)
def _fresh_public_limiter():
    yield


@pytest.fixture(autouse=True)
def _jobs_inline():
    yield


@pytest.fixture(autouse=True)
def _good_face_analysis():
    yield


PROHIBIDO = "app.golden-eventos.com"
PERMITIDOS = ("staging", "localhost", "127.0.0.1")


def validar_destino(url: str) -> str:
    """Candado contra producción: niega todo host de producción y todo lo que no sea staging o local. Devuelve la URL sin «/» final."""
    if not url:
        raise RuntimeError("Falta E2E_BASE_URL (la dirección de STAGING).")
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        raise RuntimeError("E2E_BASE_URL no es una dirección válida.")
    if PROHIBIDO in host:
        raise RuntimeError("PROHIBIDO: E2E_BASE_URL apunta a producción. Estas pruebas solo corren contra STAGING.")
    if not any(p in host for p in PERMITIDOS):
        raise RuntimeError("E2E_BASE_URL debe ser de STAGING (el host debe contener «staging») o local (localhost / 127.0.0.1).")
    return url.rstrip("/")


ARTEFACTOS = os.path.join(os.path.dirname(__file__), "artefactos")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Si una prueba falla, guarda una captura de la página (y el video queda en la misma carpeta)."""
    salida = yield
    rep = salida.get_result()
    if rep.when == "call" and rep.failed:
        for nombre in ("admin", "digitador", "anon"):
            page = item.funcargs.get(nombre) if hasattr(item, "funcargs") else None
            if page is not None:
                try:
                    os.makedirs(ARTEFACTOS, exist_ok=True)
                    page.screenshot(path=os.path.join(ARTEFACTOS, f"{item.name}-{nombre}.png".replace("/", "_")), full_page=True)
                except Exception:
                    pass


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: prueba de extremo a extremo con navegador")


def post_json(req, url, cuerpo, metodo="post"):
    return getattr(req, metodo)(url, data=json.dumps(cuerpo), headers={"Content-Type": "application/json"})


def post_form(req, url, campos):
    return req.post(url, data=urlencode(campos), headers={"Content-Type": "application/x-www-form-urlencoded"})


def como_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


@pytest.fixture(scope="session")
def base_url() -> str:
    return validar_destino(os.environ.get("E2E_BASE_URL", ""))


@pytest.fixture(scope="session")
def playwright_inst():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_inst):
    b = playwright_inst.chromium.launch(headless=True)
    yield b
    b.close()


def _credenciales(prefijo: str):
    u, c = os.environ.get(f"{prefijo}_USER", ""), os.environ.get(f"{prefijo}_PASSWORD", "")
    return (u, c) if u and c else None


def _entrar(browser, base_url, cred):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="es-CO", base_url=base_url, record_video_dir=os.path.join(ARTEFACTOS, "video"))
    page = ctx.new_page()
    page.goto("/login")
    page.fill("#usuario", cred[0])
    page.fill("#clave", cred[1])
    page.click("form[action='/login'] button[type=submit]")
    page.wait_for_load_state("networkidle")
    if "/login" in page.url and page.locator("#clave").count():
        ctx.close()
        pytest.fail("No se pudo iniciar sesión con la cuenta de pruebas (¿usuario o clave incorrectos, o cuenta bloqueada?).")
    return ctx, page


@pytest.fixture
def anon(browser, base_url):
    ctx = browser.new_context(base_url=base_url, locale="es-CO", record_video_dir=os.path.join(ARTEFACTOS, "video"))
    yield ctx.new_page()
    ctx.close()


@pytest.fixture
def admin(browser, base_url):
    cred = _credenciales("E2E")
    if not cred:
        pytest.skip("Faltan E2E_USER y E2E_PASSWORD (cuenta de pruebas de staging): se salta esta prueba.")
    ctx, page = _entrar(browser, base_url, cred)
    yield page
    ctx.close()


@pytest.fixture
def digitador(browser, base_url):
    cred = _credenciales("E2E_DIGITADOR")
    if not cred:
        pytest.skip("Faltan E2E_DIGITADOR_USER y E2E_DIGITADOR_PASSWORD (opcionales): se salta esta prueba.")
    ctx, page = _entrar(browser, base_url, cred)
    yield page
    ctx.close()


# Columnas de siempre de «Nuevo evento» (van en el nivel superior); cualquier otra clave de la plantilla es un campo personalizado y va en `extra`.
_BASE_TOP = {"event_code", "name", "location", "address", "country", "city", "start_date", "end_date", "setup_date", "event_time_start", "event_time_end",
             "setup_time_start", "setup_time_end", "coordinator_staff_id", "commercial_staff_id", "super_event_id", "event_type_id", "notes"}
_HORAS = {"event_time_start": "09:00", "event_time_end": "18:00", "setup_time_start": "06:00", "setup_time_end": "08:00"}


def _campos_obligatorios(req, hoy: str) -> dict:
    """Lo que la PLANTILLA de staging exige para crear un evento (país, ciudad, horas, coordinador, comercial, categoría, campos personalizados…), con valores
    sintéticos según el tipo de cada campo. Si la plantilla cambia, la prueba se adapta sola. Lo que no se puede inventar (p. ej. un superevento obligatorio) se omite
    y el servidor dirá qué falta (la prueba se salta con ese motivo)."""
    r = req.get("/api/event-template")
    if not r.ok:
        return {}
    tpl = como_json(r)
    personas = tpl.get("people") or {}
    en_vista = {k for sec in (tpl.get("creation_layout") or {}).get("sections", []) for k in sec.get("keys", [])}
    tipos = []
    if any(f.get("type") == "event_type" and f.get("required") and f["key"] in en_vista for f in tpl.get("fields", [])):
        rt = req.get("/api/event-types")
        datos = como_json(rt)
        tipos = datos.get("items", datos.get("types", [])) if isinstance(datos, dict) else datos
    top, extra = {}, {}
    for f in tpl.get("fields", []):
        k, t = f["key"], f.get("type")
        if f.get("retired") or not f.get("required") or k not in en_vista or t in ("switch", "workday", "client"):
            continue
        if k in ("name", "event_code", "start_date", "end_date", "setup_date"):
            continue
        valor = None
        if t == "country":
            valor = "Colombia"
        elif t == "city":
            valor = "Bogotá"
        elif t in ("text_short", "text_long"):
            valor = "Prueba E2E"
        elif t == "select":
            valor = (f.get("options") or [None])[0]
        elif t in ("money", "number"):
            valor = 1
        elif t == "time":
            valor = _HORAS.get(k, "09:00")
        elif t == "date":
            valor = hoy
        elif t == "datetime":
            valor = f"{hoy}T09:00"
        elif t == "coordinator":
            valor = (personas.get("coordinator") or [{}])[0].get("id")
        elif t == "commercial":
            valor = (personas.get("commercial") or [{}])[0].get("id")
        elif t == "event_type":
            valor = (tipos or [{}])[0].get("id")
        elif t == "address_map":
            valor = {"text": "Calle 1 # 2-3", "lat": None, "lng": None}
        elif t == "contact":
            valor = {"name": "Prueba E2E", "phone": "3001234567"}
        elif t == "bandana_colors":
            valor = [{"name": "Rojo", "hex": "#c0392b"}]
        if valor is None:
            continue
        if k == "address" and isinstance(valor, dict):
            valor = valor["text"]
        if k in _BASE_TOP:
            top[k] = valor
        elif k == "bandana":
            top["bandana_color"], top["bandana_color_name"] = valor[0]["hex"], valor[0]["name"]
        else:
            extra[k] = valor
    if extra:
        top["extra"] = extra
    return top



@pytest.fixture
def evento(admin):
    """Evento sintético «E2E-<fecha>-<sufijo>» (trae la persona PRUEBA). Al terminar lo finaliza, archiva y, si la cuenta es super_admin, lo borra."""
    req = admin.context.request
    tenant = os.environ.get("E2E_TENANT_ID", "")
    if not tenant:
        r = req.get("/api/tenants")
        lista = como_json(r)
        lista = lista.get("items", []) if isinstance(lista, dict) else lista
        if not r.ok or not lista:
            pytest.skip("No hay clientes visibles en staging para esta cuenta: define E2E_TENANT_ID.")
        tenant = str(lista[0].get("id"))
    nombre = f"E2E-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:6]}"
    hoy = datetime.date.today().isoformat()
    cuerpo = {"tenant_id": tenant, "name": nombre, "start_date": hoy, "end_date": hoy, "setup_date": hoy}
    cuerpo.update(_campos_obligatorios(req, hoy))
    r = post_json(req, "/api/events", cuerpo)
    if not r.ok:
        pytest.skip(f"No se pudo crear el evento sintético ({r.status}). La plantilla de eventos de staging quizá pide más campos: {r.text()[:200]}")
    ev = como_json(r)
    ev_id = ev.get("id") or (ev.get("event") or {}).get("id")
    assert ev_id, "La API no devolvió el id del evento sintético"
    yield {"id": ev_id, "name": nombre, "tenant": tenant}
    try:  # la limpieza nunca debe tapar el resultado de la prueba
        post_json(req, f"/api/events/{ev_id}", {"status": "finalizado"}, "patch")
        req.post(f"/api/events/{ev_id}/archive")
        req.delete(f"/api/events/{ev_id}")  # solo super_admin; si no, queda archivado con el prefijo E2E-
    except Exception:
        pass


@pytest.fixture
def evento_en_proceso(evento, admin):
    r = post_json(admin.context.request, f"/api/events/{evento['id']}", {"status": "en_proceso"}, "patch")
    assert r.ok, f"No se pudo activar el evento sintético: {r.status} {r.text()[:200]}"
    return evento


def cedula_sintetica() -> str:
    """Cédula inventada de 10 dígitos que casi seguro no existe."""
    return "99" + str(uuid.uuid4().int)[:8]
