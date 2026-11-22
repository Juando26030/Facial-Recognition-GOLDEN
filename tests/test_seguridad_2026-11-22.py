"""Revisión de seguridad del 22-nov-2026 (docs/revision_2026-11-22/03_seguridad_nube.md). Pruebas de TEXTO y de árbol sintáctico: no levantan la app ni tocan la base
(`python3 -m pytest --noconftest -q tests/test_seguridad_2026-11-22.py`). Fijan lo que la revisión comprobó, para que un cambio futuro no lo deshaga sin que se note:

  1. Toda ruta de `app/routers/` sin dependencia de autenticación está en la lista de rutas PÚBLICAS conocidas (una ruta nueva sin `Depends(...)` de sesión/token
     hace fallar la prueba hasta que se agregue aquí a propósito).
  2. Toda ruta `/internal/*` exige el token OIDC de Google (`google_invoker`) y nada más.
  3. Cabeceras: HSTS con `includeSubDomains`; CSRF rechaza `Origin: null`; cookie de sesión `SameSite=Lax` y solo https en producción.
  4. Todo JSON que una plantilla imprime con `| safe` dentro de <script> sale de un `json.dumps(...)` que escapa `</` (un valor con `</script>` no corta el bloque).
  5. Ningún cliente HTTP del código apaga la verificación TLS.
"""
import ast
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = open(os.path.join(ROOT, "app", "main.py"), encoding="utf8").read()

# Rutas que NO llevan sesión ni token por diseño (formularios públicos, enlaces por token, salud, inicio de sesión…). (archivo, método, ruta tal como la declara el router.)
PUBLIC_ROUTES = {
    ("aceptar.py", "GET", "/api/aceptar/{code}/logo"), ("aceptar.py", "GET", "/aceptar/{code}"), ("aceptar.py", "GET", "/aceptar/{code}/{token}"),
    ("aceptar.py", "GET", "/api/aceptar/{code}/text"), ("aceptar.py", "POST", "/api/aceptar/{code}/check"), ("aceptar.py", "POST", "/api/aceptar/{code}"),
    ("auth.py", "GET", "/login"), ("auth.py", "POST", "/login"), ("auth.py", "GET", "/api/session/idle"), ("auth.py", "POST", "/api/session/touch"),
    ("auth.py", "POST", "/logout"), ("auth.py", "GET", "/api/password-policy"), ("auth.py", "GET", "/olvide-contrasena"), ("auth.py", "POST", "/olvide-contrasena"),
    ("auth.py", "GET", "/restablecer/{token}"), ("auth.py", "POST", "/restablecer/{token}"), ("auth.py", "GET", "/cambiar-contrasena"), ("auth.py", "POST", "/cambiar-contrasena"),
    ("certificates_public.py", "GET", "/c/{token}"), ("certificates_public.py", "GET", "/c/{token}/lookup"), ("certificates_public.py", "GET", "/c/{token}/asset/{tenant_id}/{filename}"),
    ("clean_url.py", "GET", "/{evento}"), ("clean_url.py", "GET", "/{evento}/{formulario}"),
    ("contacts.py", "GET", "/contacto/{token}"), ("contacts.py", "GET", "/contacto/{token}/data"), ("contacts.py", "POST", "/contacto/{token}/share"),
    ("contacts.py", "GET", "/tarjeta/{token}"), ("contacts.py", "GET", "/tarjeta/{token}/data"), ("contacts.py", "GET", "/tarjeta/{token}/vcard"),
    ("contacts.py", "GET", "/expositor/{token}"), ("contacts.py", "GET", "/expositor/{token}/data"), ("contacts.py", "POST", "/expositor/{token}/scan"),
    ("contacts.py", "GET", "/expositor/{token}/vcard/{share}"), ("contacts.py", "GET", "/expositor/{token}/leads.xlsx"),
    ("delivery.py", "GET", "/entrega/{token}"), ("delivery.py", "POST", "/entrega/{token}/encuesta"), ("delivery.py", "GET", "/entrega/{token}/base"),
    ("digital_public.py", "GET", "/b/{token}"), ("digital_public.py", "GET", "/b/{token}/contact"), ("digital_public.py", "GET", "/b/{token}/data"),
    ("digital_public.py", "GET", "/b/{token}/qr"), ("digital_public.py", "GET", "/b/{token}/wallet/google"), ("digital_public.py", "GET", "/b/{token}/wallet/apple"),
    ("digital_public.py", "GET", "/b/{token}/asset/{tenant_id}/{filename}"), ("digital_public.py", "GET", "/b/{token}/photo"),
    ("form_payments.py", "POST", "/f/{event_id}/{slug}/quote"), ("form_payments.py", "GET", "/f/{event_id}/{slug}/rates"), ("form_payments.py", "POST", "/f/{event_id}/{slug}/pay/confirm"),
    ("form_payments.py", "GET", "/f/{event_id}/{slug}/pay/status"), ("form_payments.py", "POST", "/webhooks/wompi/{ref}"), ("form_payments.py", "POST", "/webhooks/wompi"),
    ("forms_public.py", "GET", "/f/{event_id}/{slug}"), ("forms_public.py", "GET", "/f/{event_id}/{slug}/state"), ("forms_public.py", "POST", "/f/{event_id}/{slug}/gate"),
    ("forms_public.py", "POST", "/f/{event_id}/{slug}/lookup"), ("forms_public.py", "POST", "/f/{event_id}/{slug}/check"), ("forms_public.py", "POST", "/f/{event_id}/{slug}/beacon"),
    ("forms_public.py", "GET", "/f/{event_id}/{slug}/asset/{tenant_id}/{filename}"), ("forms_public.py", "POST", "/f/{event_id}/{slug}/upload"), ("forms_public.py", "POST", "/f/{event_id}/{slug}/submit"),
    ("legal_public.py", "GET", "/privacidad"), ("legal_public.py", "GET", "/privacidad/v1.0"), ("legal_public.py", "GET", "/terminos"), ("legal_public.py", "GET", "/reembolsos"),
    ("local_cert.py", "GET", "/certificado"), ("local_cert.py", "GET", "/certificado/golden-local-ca.cer"), ("local_cert.py", "GET", "/certificado/instalar-windows.cmd"),
    ("login_approval.py", "GET", "/ingreso/espera"), ("login_approval.py", "POST", "/api/ingreso/estado"), ("login_approval.py", "POST", "/api/ingreso/cancelar"),
    ("nodes.py", "POST", "/node/enroll"),          # usuario+contraseña+llave de producto en el cuerpo (mismos límites que /login)
    ("ops.py", "GET", "/health"), ("ops.py", "GET", "/healthz"), ("ops.py", "GET", "/ready"), ("ops.py", "GET", "/readyz"), ("ops.py", "GET", "/api/ops/version"),
    ("ops.py", "GET", "/api/ops/version-check"), ("ops.py", "GET", "/api/ops/local-address"), ("ops.py", "GET", "/api/ops/server-id"),          # (piden sesión dentro del cuerpo, sin base)
    ("ops.py", "GET", "/api/ops/update-manifest"), ("ops.py", "GET", "/api/ops/update-package/{name}"), ("ops.py", "GET", "/api/ops/update-status"), ("ops.py", "GET", "/sistema"),
    ("parametros.py", "GET", "/email-assets/{tenant_id}/{filename}"),          # imágenes de correos: nombre UUID
    ("queue.py", "GET", "/turno/{event_id}"), ("queue.py", "POST", "/turno/{event_id}/buscar"), ("queue.py", "GET", "/turno/{event_id}/{token}"), ("queue.py", "GET", "/turno/{event_id}/{token}/state"),
    ("reprint.py", "GET", "/reimpresion/{token}"), ("reprint.py", "POST", "/reimpresion/{token}"),
    ("roulette.py", "GET", "/r/{token}"), ("roulette.py", "GET", "/r/{token}/state"), ("roulette.py", "POST", "/r/{token}/spin"), ("roulette.py", "GET", "/r/{token}/asset/{tenant_id}/{filename}"),
    ("server_keys.py", "POST", "/node/key/claim"),
    ("stats_links.py", "GET", "/ver/e/{token}"), ("stats_links.py", "GET", "/ver/tv/{token}"), ("stats_links.py", "GET", "/api/ver/{token}/tv"), ("stats_links.py", "GET", "/api/ver/{token}/logo"),
    ("stats_links.py", "GET", "/ver/f/{token}"), ("stats_links.py", "GET", "/api/ver/{token}/stats/variables"), ("stats_links.py", "GET", "/api/ver/{token}/stats/data"),
    ("stats_links.py", "GET", "/api/ver/{token}/analytics/registro"), ("stats_links.py", "GET", "/api/ver/{token}/form-stats"),
    ("uploads.py", "PUT", "/uploads/local/{token}"),          # token firmado con SECRET_KEY en la propia ruta
}


def _routes():
    """(archivo, método, ruta, nombre de la función, dependencias distintas de get_db) de cada ruta declarada en app/routers/*.py (también las del router entero)."""
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "app", "routers", "*.py"))):
        src = open(path, encoding="utf8").read()
        tree = ast.parse(src)
        router_deps = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "dependencies" and isinstance(node.targets[0], ast.Name):
                        router_deps[node.targets[0].id] = ast.unparse(kw.value)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            deps = []
            for d in node.args.defaults + node.args.kw_defaults:
                if isinstance(d, ast.Call) and getattr(d.func, "id", None) == "Depends" and d.args:
                    deps.append(ast.unparse(d.args[0]))
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "delete", "patch") and dec.args:
                    rname = ast.unparse(dec.func.value)
                    all_deps = [d for d in deps if d != "get_db"] + ([router_deps[rname]] if rname in router_deps else [])
                    out.append((os.path.basename(path), dec.func.attr.upper(), ast.unparse(dec.args[0]).strip("'\""), node.name, all_deps))
    return out


def test_rutas_sin_autenticacion_son_solo_las_publicas_conocidas():
    rows = _routes()
    assert len(rows) > 700, "la lectura de rutas falló (muy pocas rutas)"
    sin_auth = {(f, m, p) for f, m, p, _fn, deps in rows if not deps}
    nuevas = sorted(sin_auth - PUBLIC_ROUTES)
    assert not nuevas, f"Rutas sin dependencia de sesión/token que no están en la lista de públicas conocidas (agregar a propósito o proteger): {nuevas}"
    desaparecidas = sorted(PUBLIC_ROUTES - {(f, m, p) for f, m, p, _fn, _d in rows})
    assert not desaparecidas, f"La lista de rutas públicas tiene entradas que ya no existen (limpiar): {desaparecidas}"


def test_rutas_internal_solo_con_oidc_de_google():
    internas = [(f, m, p, deps) for f, m, p, _fn, deps in _routes() if p.startswith("/internal")]
    assert internas, "no se encontraron rutas /internal/*"
    for f, m, p, deps in internas:
        assert deps == ["google_invoker"], f"{m} {p} ({f}) debe depender SOLO de google_invoker: {deps}"


def test_hsts_incluye_subdominios_en_produccion():
    m = re.search(r'setdefault\("Strict-Transport-Security", "([^"]+)"\)', MAIN)
    assert m, "falta la cabecera HSTS en app/main.py"
    assert "max-age=31536000" in m.group(1) and "includeSubDomains" in m.group(1)
    assert re.search(r"if IS_PRODUCTION:\n\s+h\.setdefault\(\"Strict-Transport-Security\"", MAIN), "HSTS solo en producción (en desarrollo no hay https)"


def test_csrf_rechaza_origin_null_y_compara_con_el_host():
    gate = MAIN.split("async def csrf_and_password_gate", 1)[1].split("@app.middleware", 1)[0]
    assert 'elif origin == "null":' in gate and "Origen no permitido" in gate
    assert 'request.headers.get("host")' in gate and 'urlsplit(public).netloc' in gate


def test_cookie_de_sesion_lax_httponly_y_segura_en_produccion():
    block = MAIN.split("SessionMiddleware,", 1)[1].split("\n)", 1)[0]
    assert 'same_site="lax"' in block and "https_only=IS_PRODUCTION" in block
    assert "httponly" not in block.lower(), "no desactivar HttpOnly (Starlette lo pone por defecto)"


def test_json_en_script_escapa_cierre_de_etiqueta():
    """Cada `{{ x_json | safe }}` de las plantillas sale de un json.dumps(...).replace('</', '<\\/') (o es el literal 'null')."""
    names = set()
    for path in glob.glob(os.path.join(ROOT, "templates", "*.html")):
        names.update(re.findall(r"\{\{\s*(\w+_json)\s*\|\s*safe\s*\}\}", open(path, encoding="utf8").read()))
    assert names, "no se encontraron JSON con | safe en las plantillas"
    sources = {p: open(p, encoding="utf8").read() for p in glob.glob(os.path.join(ROOT, "app", "**", "*.py"), recursive=True)}
    for name in sorted(names):
        lines = [ln for src in sources.values() for ln in src.splitlines() if re.search(rf"\b{name}\b", ln) and "json.dumps" in ln]
        assert lines, f"no se encontró dónde se construye {name}"
        for ln in lines:
            assert '.replace("</", "<\\\\/")' in ln, f"{name}: json.dumps sin escapar '</': {ln.strip()[:120]}"


def test_ningun_cliente_http_apaga_la_verificacion_tls():
    for path in glob.glob(os.path.join(ROOT, "app", "**", "*.py"), recursive=True):
        src = open(path, encoding="utf8").read()
        assert "verify=False" not in src and "CERT_NONE" not in src and "_create_unverified" not in src, path
