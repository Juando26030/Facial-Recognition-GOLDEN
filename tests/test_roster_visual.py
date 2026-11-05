"""Adjuntar Base de Datos (kiosk_roster.html) cumple el estándar visual (docs/ux/ESTANDARES_VISUALES.md): pruebas de archivos, sin base ni servidor."""
import pathlib
import re

PAGE = pathlib.Path("templates/kiosk_roster.html").read_text(encoding="utf-8")
PBAR = pathlib.Path("static/js/progress-bar.js").read_text(encoding="utf-8")
CSS = pathlib.Path("static/css/design-system.css").read_text(encoding="utf-8")
GUIDE = pathlib.Path("docs/ux/guia_visual.html").read_text(encoding="utf-8")
EMOJI = re.compile("[←-⇿⌀-⏿①-➿⤀-⥿⬀-⯿\U0001f000-\U0001faff️]")


def test_the_page_uses_the_base_and_has_no_emoji_icons():
    assert '<body class="gw-page' in PAGE and '{% include "_gw_head.html" %}' in PAGE
    assert "css/design-system.css" not in PAGE.replace("_gw_head", "")                      # la base entra por _gw_head.html
    bad = sorted({c for c in PAGE if EMOJI.match(c) and c not in "→"})                 # la flecha → del informe de columnas es texto, no ícono
    assert not bad, f"emojis como ícono: {bad}"
    assert "img/icons.svg" in PAGE and "#i-alert" in PAGE and 'ico: "error"' in PAGE and 'ico: "info"' in PAGE


def test_no_inline_colors_sizes_radii_or_handlers():
    assert not re.search(r"\bstyle\s*=", PAGE), "estilos en línea"
    assert ".style.cssText" not in PAGE and "style.display" not in PAGE
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"&#\d+;", "", PAGE)), "colores sueltos"
    assert not re.search(r"(?<![\w-])\d+(\.\d+)?\s?(px|rem|em)\b", re.sub(r"<script.*?</script>", "", PAGE, flags=re.S)), "tamaños sueltos en el HTML"
    assert not re.search(r"\bon[a-z]+\s*=", re.sub(r"\.on[a-z]+\s*=", "", PAGE)), "manejadores en línea"
    assert not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", PAGE)


def test_the_progress_bar_uses_classes_not_colors():
    assert "gw-pbar" in PBAR and not re.search(r"#[0-9a-fA-F]{3,6}\b", PBAR) and "cssText" not in PBAR
    for cls in (".gw-pbar", ".gw-pbar--ok", ".gw-pbar--err", ".gw-step", ".gw-step__num", ".gw-checklist", ".gw-shell", ".gw-list"):
        assert cls + " " in CSS or cls + "," in CSS, cls
        assert cls.lstrip(".") in GUIDE or cls.lstrip(".") + "__" in GUIDE, cls


def test_every_control_has_a_label_and_the_steps_and_single_primary_button_exist():
    for fid in re.findall(r'<(?:input|select)\b[^>]*\bid="([^"]+)"', PAGE):
        assert f'for="{fid}"' in PAGE, f"control sin label for: {fid}"
    assert 'for="overwriteBirth"' in PAGE and "overwrite_birth_label" in PAGE
    assert PAGE.count("gw-btn--primary") == 1 and "Cargar lista" in PAGE
    assert "Elige el archivo" in PAGE and ">Revisa<" in PAGE and ">Cargar<" in PAGE
    for jargon in ("staff_role}}", "encoding", "serial"):
        assert jargon not in re.sub(r"<script.*?</script>|<!--.*?-->|\{\{.*?\}\}", "", PAGE, flags=re.S).replace("staff_role}}", ""), jargon
