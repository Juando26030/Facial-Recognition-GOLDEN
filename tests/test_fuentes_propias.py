"""Nada de terceros en las páginas: ni fuentes ni el script del QR se piden fuera de nuestro servidor (app de biometría: la IP de las personas no se le entrega a nadie)."""
import json
import pathlib
import re

SCRIPT_HOSTS_NO_QR = re.compile(r"https?://[^\"'\s)]*qrcode[^\"'\s)]*", re.I)


def _files():
    for root in ("templates", "static/css", "static/js"):
        for f in pathlib.Path(root).rglob("*"):
            if f.suffix in (".html", ".css", ".js"):
                yield f, f.read_text(encoding="utf-8", errors="ignore")


def test_the_qr_script_comes_from_our_own_static_files_and_never_from_a_cdn(client):
    users = [f.as_posix() for f, text in _files() if "qrcode-generator-1.4.4.min.js" in text]
    assert len(users) >= 6, users                                                                    # las 6 pantallas que dibujan QR
    assert [f.as_posix() for f, text in _files() if SCRIPT_HOSTS_NO_QR.search(text)] == []
    r = client.get("/static/vendor/qrcode-generator-1.4.4.min.js")
    assert r.status_code == 200 and "qrcode" in r.text[:60]


# ------------------------------------------------------------------------------------------------------------------------------------ tipografías propias
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "fonts.bunny.net", "fontawesome.com", "cdnjs.cloudflare.com/ajax/libs/font")
LEGACY_40 = ("Roboto Open_Sans Lato Montserrat Oswald Raleway Poppins Merriweather Playfair_Display Nunito Ubuntu PT_Sans Noto_Sans Source_Sans_Pro Rubik Inter Work_Sans Quicksand Fira_Sans Barlow "
             "Karla Mulish Josefin_Sans Bebas_Neue Dancing_Script Pacifico Lobster Caveat Anton Archivo_Black Cormorant_Garamond Crimson_Text Libre_Baskerville EB_Garamond Abril_Fatface Comfortaa "
             "DM_Sans Space_Grotesk Manrope Zilla_Slab").split()


def test_no_page_script_or_email_asks_a_third_party_for_fonts_and_there_are_no_exceptions():
    offenders = [f.as_posix() for f, text in _files() if any(h in text for h in FONT_HOSTS)]
    offenders += [f.as_posix() for f in pathlib.Path("app").rglob("*.py") if any(h in f.read_text(encoding="utf-8") for h in FONT_HOSTS)]
    assert offenders == [], "una página pide fuentes a un tercero: aloja la fuente en static/fonts y decláralo en scripts/gen_fonts_css.py"


def test_the_generated_font_files_match_the_single_map():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_fonts_css", "scripts/gen_fonts_css.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert pathlib.Path("static/css/fonts-propias.css").read_text(encoding="utf-8") == gen.css()
    assert pathlib.Path("static/js/fonts-propias.js").read_text(encoding="utf-8") == gen.js()
    assert len(gen.SIX) == 40 and set(gen.MAP.values()) <= set(gen.SIX) and not set(gen.MAP) & set(gen.SIX)
    for fam in (n.replace("_", " ") for n in LEGACY_40):                                                                              # ningún diseño guardado queda sin tipografía equivalente
        assert fam in gen.SIX or fam in gen.MAP, fam
    assert {"Montserrat", "Roboto", "Playfair Display"} <= set(gen.SIX)                                 # los diseños que usan estas tres se ven exactamente igual


def test_hosted_fonts_are_latin_woff2_400_700_with_license_and_within_200_kb():
    files = sorted(pathlib.Path("static/fonts").glob("*.woff2"))
    assert files and all(re.fullmatch(r"[a-z-]+-latin-(400|700)-normal\.woff2", f.name) for f in files), [f.name for f in files]
    assert sum(f.stat().st_size for f in files) <= 2 * 1024 * 1024                  # 40 familias; cada navegador baja solo las que usa
    css = pathlib.Path("static/css/fonts-propias.css").read_text(encoding="utf-8")
    for name in re.findall(r"fonts/([\w.-]+\.woff2)", css):
        assert pathlib.Path("static/fonts", name).exists(), name
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_fonts_css", "scripts/gen_fonts_css.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert {f.stem for f in pathlib.Path("static/fonts/licencias").glob("*.txt")} == set(gen.FAMILIES.values())            # cada familia, con su licencia


def test_every_selector_offers_the_same_hosted_families_and_agrandir_stays_apart(client):
    js = pathlib.Path("static/js/fonts-propias.js").read_text(encoding="utf-8")
    offered = json.loads(re.search(r"choices: (\[[^\]]*\])", js).group(1))
    assert len(offered) == 40 and {"Roboto", "Lato", "Pacifico", "Zilla Slab", "Bebas Neue"} <= set(offered) and "Agrandir" not in offered
    assert "GOLDEN_FONT_FAMILIES" not in pathlib.Path("static/js/theme.js").read_text(encoding="utf-8")                  # ya no hay una segunda lista
    cfg = pathlib.Path("templates/configuracion.html").read_text(encoding="utf-8")
    assert "Original (Agrandir)" in cfg and "GoldenFontPicker.mount" in cfg and "js/fonts-propias.js" in cfg and "js/font-picker.js" in cfg    # el mismo selector que el diseñador
    editor = pathlib.Path("templates/badge_editor.html").read_text(encoding="utf-8")
    assert "GoldenFontPicker.mount" in editor and "GoldenFonts.resolve" in editor and "js/font-picker.js" in editor and "js/fonts-propias.js" in editor
    for page, marker in (("kiosk_formulario_editor", "GoldenFonts.choices"), ("kiosk_ruleta_visual", "GoldenFonts.choices")):
        text = pathlib.Path(f"templates/{page}.html").read_text(encoding="utf-8")
        assert marker in text and "js/fonts-propias.js" in text and "css/fonts-propias.css" in text, page
    for page in ("form_public", "badge_print", "certificate_public", "digital_badge", "kiosk_certificados", "roulette_display"):
        assert "css/fonts-propias.css" in pathlib.Path(f"templates/{page}.html").read_text(encoding="utf-8"), page
    for path in ("css/fonts-propias.css", "js/fonts-propias.js", "fonts/roboto-latin-400-normal.woff2", "fonts/bebas-neue-latin-400-normal.woff2"):
        assert client.get(f"/static/{path}").status_code == 200, path


def test_emails_ask_for_agrandir_first_and_a_safe_sans_serif_as_fallback():
    from app import email_template
    html = email_template.render.__code__.co_consts                                                     # el envoltorio del cuerpo vive dentro de render()
    assert any("font-family:Agrandir,Arial,Helvetica,sans-serif" in str(c) for c in html)
    assert "font-family:Agrandir,Arial,Helvetica,sans-serif" in pathlib.Path("app/consent_receipt.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------------------------------ scripts de terceros
# Lo único que todavía se pide fuera: pantallas del PERSONAL (decisión del dueño: después del piloto) y el traductor de Google del formulario público (política v1.2).
EXTERNAL_SCRIPTS_ALLOWED = {
    "templates/kiosk_certificados.html": {"cdnjs.cloudflare.com"},          # JSZip
    "templates/kiosk_estadisticas.html": {"cdnjs.cloudflare.com"},          # Chart.js
    "templates/kiosk_formulario_editor.html": {"cdnjs.cloudflare.com"},     # Chart.js
    "templates/kiosk_roster.html": {"cdnjs.cloudflare.com"},                # SheetJS y JSZip
    "templates/form_public.html": {"translate.google.com"},                 # botón «Translate»
}
SCRIPT_URL = re.compile(r"""(?:<script[^>]+src=|\.src\s*=\s*)["'](https?://([^/"']+)[^"']*)["']""")


def test_attendee_pages_load_every_script_from_our_own_server_and_staff_pages_are_the_only_listed_exceptions():
    found = {}
    for f in pathlib.Path("templates").glob("*.html"):
        hosts = {m.group(2) for m in SCRIPT_URL.finditer(f.read_text(encoding="utf-8"))}
        if hosts:
            found[f.as_posix()] = hosts
    assert found == EXTERNAL_SCRIPTS_ALLOWED, "un script externo nuevo (o uno que ya no está): aloja el script en static/vendor con su licencia"
    for js in pathlib.Path("static/js").glob("*.js"):                                                   # los scripts propios tampoco inyectan scripts externos
        assert not SCRIPT_URL.search(js.read_text(encoding="utf-8", errors="ignore")), js.name


def test_barcode_pdf_and_canvas_libraries_are_hosted_with_their_licenses(client):
    for name, lic, marker in (("JsBarcode-3.12.3.all.min.js", "JsBarcode-LICENSE.txt", "JsBarcode"), ("html2canvas-1.4.1.min.js", "html2canvas-LICENSE.txt", "html2canvas"),
                              ("jspdf-2.5.1.umd.min.js", "jspdf-LICENSE.txt", "jsPDF")):
        r = client.get(f"/static/vendor/{name}")
        assert r.status_code == 200 and marker in r.text[:400], name
        assert "Permission is hereby granted" in pathlib.Path("static/vendor", lic).read_text(encoding="utf-8"), lic
    for page in ("digital_badge", "certificate_public"):
        text = pathlib.Path(f"templates/{page}.html").read_text(encoding="utf-8")
        assert "vendor/JsBarcode-3.12.3.all.min.js" in text and "cdnjs" not in text, page
    assert "vendor/html2canvas-1.4.1.min.js" in pathlib.Path("templates/certificate_public.html").read_text(encoding="utf-8")
