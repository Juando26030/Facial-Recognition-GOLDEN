"""SEO de la plataforma (22-nov-2026, docs/revision_2026-11-22/08 P1-P3 y 11): app.golden-eventos.com no compite con el sitio corporativo.
Los buscadores solo indexan las tres páginas legales; el ingreso y las páginas públicas personales llevan «noindex». Pruebas de texto (sin base)."""
import ast
from pathlib import Path

from app import appmode

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
LEGAL = ["legal_base.html", "legal_privacidad.html", "legal_privacidad_v11.html", "legal_terminos.html", "legal_reembolsos.html", "_legal_footer.html"]
# Páginas que se abren sin sesión y no deben salir en buscadores.
NOINDEX = ["login.html", "password.html", "ingreso_espera.html", "certificado_local.html", "form_public.html", "form_stats.html", "aceptar.html", "aceptar_no_disponible.html",
           "digital_badge.html", "certificate_public.html", "entrega.html", "turno_public.html", "roulette_display.html", "kiosk_autoregistro.html", "kiosk_tv.html",
           "kiosk_turnos_tv.html", "kiosk_estadisticas.html", "_contact_public_head.html"]


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _robots_txt() -> str:
    """El texto de robots.txt, evaluado del módulo sin importarlo (importarlo no hace falta y así la prueba no depende de FastAPI)."""
    tree = ast.parse((ROOT / "app" / "routers" / "legal_public.py").read_text(encoding="utf-8"))
    ns: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("INDEXABLE_PATHS", "CORPORATE_SITEMAP", "ROBOTS_TXT"):
            exec(compile(ast.Module([node], []), "legal_public", "exec"), ns)
    return ns["ROBOTS_TXT"]


def test_robots_txt_solo_deja_entrar_a_las_paginas_legales():
    lines = _robots_txt().splitlines()
    assert lines[0] == "User-agent: *" and "Disallow: /" in lines
    assert [ln for ln in lines if ln.startswith("Allow:")] == ["Allow: /privacidad$", "Allow: /terminos$", "Allow: /reembolsos$"]
    assert "Sitemap: https://golden-eventos.com/sitemap.xml" in lines
    assert not any("login" in ln or "/f/" in ln for ln in lines)


def test_robots_txt_es_una_ruta_sin_base_ni_sesion_y_se_guarda_una_hora():
    src = (ROOT / "app" / "routers" / "legal_public.py").read_text(encoding="utf-8")
    fn = src.split('@router.get("/robots.txt"', 1)[1].split("@router.get", 1)[0]
    assert "def robots_txt():" in fn and "async def" not in fn
    assert "max-age=3600" in fn and "SessionLocal" not in fn and "session" not in fn


def test_robots_txt_lo_sirven_publico_y_web():
    for mode in ("publico", "web", "all"):
        assert appmode.route_allowed("/robots.txt", mode=mode)


def test_rutas_legales_existen_y_estan_reservadas():
    src = (ROOT / "app" / "routers" / "legal_public.py").read_text(encoding="utf-8")
    for path in ("/privacidad", "/terminos", "/reembolsos"):
        assert f'@router.get("{path}")' in src
    slug = (ROOT / "app" / "public_slug.py").read_text(encoding="utf-8")
    assert '"robots-txt"' in slug and '"sitemap-xml"' in slug


def test_ingreso_y_paginas_publicas_personales_llevan_noindex():
    faltan = [n for n in NOINDEX if 'name="robots"' not in _read(n) or "noindex" not in _read(n)]
    assert not faltan, f"Páginas públicas sin noindex: {faltan}"
    assert '<meta name="robots" content="noindex,nofollow">' in _read("login.html")


def test_ninguna_plantilla_legal_lleva_noindex():
    con = [n for n in LEGAL if "noindex" in _read(n)]
    assert not con, f"Las páginas legales SÍ se indexan: {con}"


def test_paginas_legales_con_descripcion_canonico_y_titulo_normal():
    base = _read("legal_base.html")
    assert '<meta name="description" content="{{ page_description' in base
    assert '<link rel="canonical" href="{{ _base }}{{ canonical_path or request.url.path }}">' in base and "public_base_url(" in base
    assert "company_name|title" in base
    src = (ROOT / "app" / "routers" / "legal_public.py").read_text(encoding="utf-8")
    assert src.count('"page_description"') == 4          # las cuatro respuestas de páginas legales la envían
    assert '"canonical_path": "/privacidad"' in src      # la versión histórica apunta a la vigente
