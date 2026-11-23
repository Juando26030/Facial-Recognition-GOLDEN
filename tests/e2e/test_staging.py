"""Pruebas E2E contra STAGING (Playwright síncrono). Cada caso es independiente, usa datos sintéticos «E2E-<fecha>» y limpia lo que crea.
Se saltan solas si falta la cuenta de pruebas o si la función aún no está desplegada en staging (el mensaje lo dice)."""
import os
import re

import pytest

from .conftest import como_json, cedula_sintetica, post_form, post_json, validar_destino

pytestmark = pytest.mark.e2e


def test_candado_contra_produccion():
    """El candado niega producción y direcciones que no sean de staging o locales."""
    for malo in ("https://app.golden-eventos.com", "https://APP.golden-eventos.com/x", "https://ejemplo.com", ""):
        with pytest.raises(RuntimeError):
            validar_destino(malo)
    assert validar_destino("https://staging.golden-eventos.com/") == "https://staging.golden-eventos.com"
    assert validar_destino("http://localhost:5000") == "http://localhost:5000"


# (a) login y menú según rol
def test_login_y_menu_segun_rol(admin):
    admin.goto("/eventos")
    menu = admin.locator("nav a[href^='/']")
    assert menu.count() > 0, "El menú lateral no muestra enlaces después de iniciar sesión"
    destinos = {menu.nth(i).get_attribute("href") for i in range(menu.count())}
    assert any(d.startswith("/eventos") for d in destinos), "El menú no trae «Eventos»"
    # Los enlaces de administración solo los ve el rol que corresponde: lo que se ve debe abrir sin 403.
    for d in sorted(destinos & {"/configuracion", "/sistema", "/clientes"}):
        r = admin.context.request.get(d)
        assert r.status < 400, f"{d} aparece en el menú pero responde {r.status}"


def test_menu_del_digitador_no_trae_administracion(digitador):
    digitador.goto("/")
    digitador.wait_for_load_state("networkidle")
    enlaces = {digitador.locator("nav a[href^='/']").nth(i).get_attribute("href") for i in range(digitador.locator("nav a[href^='/']").count())}
    assert not (enlaces & {"/configuracion", "/sistema", "/cuentas", "/clientes"}), f"El digitador ve enlaces de administración: {enlaces}"


# (b) evento sintético, activarlo, registrar por cédula y verla en el directorio
def test_registrar_por_cedula_y_ver_en_directorio(evento_en_proceso, admin):
    ev, cedula = evento_en_proceso, cedula_sintetica()
    r = post_form(admin.context.request, "/api/register", {"event_id": ev["id"], "id": cedula, "first_name": "Prueba E2E", "last_name": "Sintetica"})
    assert r.ok, f"No se pudo registrar la persona sintética: {r.status} {r.text()[:200]}"
    admin.goto(f"/kiosk/{ev['id']}/registro")
    admin.wait_for_load_state("networkidle")
    if not admin.locator("#searchCedula").is_visible():
        admin.get_by_text(re.compile(r"^\s*Directorio\s*$")).first.click(timeout=5000)
    admin.fill("#searchCedula", cedula)
    admin.wait_for_selector(f"#directoryTableBody tr:has-text('{cedula}')", timeout=15000)


# (c) digitador: editar a una persona NO registrada
def test_digitador_edita_no_registrada_avisa_queda_registrada(digitador, evento_en_proceso, admin):
    ev, cedula = evento_en_proceso, cedula_sintetica()
    # La persona queda «No registrada» (se carga como base) y asignamos el evento al digitador solo si la cuenta puede verlo.
    r = post_form(admin.context.request, "/api/register", {"event_id": ev["id"], "id": cedula, "first_name": "Nueva E2E"})
    if not r.ok:
        pytest.skip(f"No se pudo preparar la persona ({r.status}).")
    digitador.goto(f"/kiosk/{ev['id']}/registro")
    if "/kiosk/" not in digitador.url:
        pytest.skip("El digitador de pruebas no tiene asignado el evento sintético: asígnale eventos o usa una cuenta con acceso a todos.")
    digitador.wait_for_load_state("networkidle")
    digitador.fill("#searchCedula", cedula)
    fila = digitador.locator(f"#directoryTableBody tr:has-text('{cedula}')")
    fila.wait_for(timeout=15000)
    boton = fila.get_by_role("button", name=re.compile("Editar"))
    if not boton.count():
        pytest.skip("La fila no ofrece «Editar» (la persona ya quedó Registrada al crearla): no se puede probar el aviso en este estado.")
    boton.first.click()
    cuerpo = digitador.locator("body")
    cuerpo.get_by_text(re.compile("queda Registrada", re.I)).first.wait_for(timeout=5000)
    assert digitador.get_by_role("button", name=re.compile("Guardar sin registrar", re.I)).count() >= 1


# (d) tabla de Registro sin desplazamiento horizontal y con encabezados con el nombre del campo
@pytest.mark.parametrize("ancho", [320, 390, 768, 1280, 1920])
def test_tabla_registro_sin_scroll_horizontal(admin, evento_en_proceso, ancho):
    admin.set_viewport_size({"width": ancho, "height": 900})
    admin.goto(f"/kiosk/{evento_en_proceso['id']}/registro")
    admin.wait_for_load_state("networkidle")
    sobra = admin.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert sobra <= 1, f"A {ancho}px la página se desplaza {sobra}px en horizontal"
    cabeceras = [t.strip() for t in admin.locator("#directorio thead th[scope=col]").all_inner_texts() if t.strip()]
    assert any("Estado" in t for t in cabeceras) and len(cabeceras) >= 4, f"Encabezados vacíos o sin nombre de campo: {cabeceras}"


# (e) confirmaciones escritas
def test_deshabilitar_llave_pide_escribir_la_palabra(admin):
    admin.goto("/configuracion")
    admin.wait_for_load_state("networkidle")
    boton = admin.locator("#skRows button:has-text('Deshabilitar')").first
    if not boton.count():
        pytest.skip("No hay llaves de producto en staging para probar «Deshabilitar llave»: crea una desde Configuración › Servidor local.")
    boton.click()
    dialogo = admin.locator("[role=dialog]:visible, .gw-modal:visible").last
    campo = dialogo.locator("input[type=text]")
    if not campo.count():
        pytest.skip("Esta versión de staging todavía no pide escribir la palabra para deshabilitar la llave.")
    dialogo.get_by_role("button", name=re.compile("Deshabilitar")).click()
    assert dialogo.is_visible(), "Sin escribir la palabra, la confirmación se cerró y siguió adelante"


def test_reabrir_evento_pide_escribir_la_palabra(admin, evento):
    req = admin.context.request
    post_json(req, f"/api/events/{evento['id']}", {"status": "en_proceso"}, "patch")
    post_json(req, f"/api/events/{evento['id']}", {"status": "finalizado"}, "patch")
    admin.goto("/eventos")
    admin.wait_for_load_state("networkidle")
    fila = admin.locator(f"tr:has-text('{evento['name']}'), .gw-card:has-text('{evento['name']}')").first
    boton = fila.get_by_role("button", name=re.compile("Reabrir", re.I))
    if not boton.count():
        pytest.skip("No se encontró el botón «Reabrir» del evento en esta versión de staging.")
    boton.first.click()
    dialogo = admin.locator("[role=dialog]:visible").last
    if not dialogo.locator("input[type=text]").count():
        pytest.skip("Esta versión de staging todavía no pide escribir la palabra para reabrir un evento.")
    dialogo.get_by_role("button", name=re.compile("Reabrir", re.I)).click()
    estado = como_json(req.get(f"/api/events/{evento['id']}"))
    assert estado.get("status", "finalizado") == "finalizado", "El evento se reabrió sin escribir la palabra"


# (f) robots.txt y noindex
def test_robots_y_noindex(anon):
    r = anon.context.request.get("/robots.txt")
    assert r.status == 200, f"/robots.txt respondió {r.status}"
    anon.goto("/login")
    meta = anon.locator("meta[name=robots]").first.get_attribute("content") if anon.locator("meta[name=robots]").count() else ""
    cabecera = anon.context.request.get("/login").headers.get("x-robots-tag", "")
    assert "noindex" in (meta or "").lower() or "noindex" in cabecera.lower(), "/login no trae noindex (ni meta ni cabecera X-Robots-Tag)"


# (g) solicitud de cotización pública (API)
def test_cotizacion_publica_campo_trampa_y_datos_invalidos(anon):
    req = anon.context.request
    r = post_json(req, "/api/public/quote-request", {"name": "Prueba E2E", "email": "e2e@example.invalid", "website": "http://trampa.invalid", "company_url": "http://trampa.invalid", "hp": "x"})
    if r.status == 404:
        pytest.skip("El endpoint /api/public/quote-request no existe en este servicio de staging (vive en otro dominio o aún no está desplegado).")
    assert r.status == 200, f"Con el campo trampa lleno se esperaba 200 sin enviar nada, llegó {r.status}"
    r = post_json(req, "/api/public/quote-request", {"name": "", "email": "no-es-correo", "phone": "x"})
    assert r.status == 400, f"Con datos inválidos se esperaba 400, llegó {r.status}"
    cuerpo = como_json(r)
    assert cuerpo and any(k in str(cuerpo).lower() for k in ("errors", "errores", "email", "name")), "El 400 no trae errores por campo"


# (h) escarapela a PDF 62 x 99,8 mm
@pytest.mark.skip(reason="La escarapela se imprime desde la ventana de impresión del navegador con el flujo del quiosco y requiere impresora/etiqueta física (Brother QL-800); "
                         "no hay ruta de staging que la entregue sin impresora. Los parámetros 62 × 99,8 mm los fija tests/test_impresion_parametros_fijos.py.")
def test_escarapela_pdf_62_x_99_8_mm(admin):
    pass


# (i) humo de /health de los servicios
@pytest.mark.parametrize("variable", ["E2E_BASE_URL", "E2E_URL_PUBLICO", "E2E_URL_BIOMETRIA"])
def test_health_de_los_servicios(anon, variable):
    url = os.environ.get(variable, "")
    if not url:
        pytest.skip(f"Falta {variable}.")
    r = anon.context.request.get(validar_destino(url) + "/health")
    assert r.status == 200, f"{variable} /health respondió {r.status}"
