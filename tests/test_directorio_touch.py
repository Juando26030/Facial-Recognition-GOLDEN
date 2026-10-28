"""Directorio en vivo con «Registro touch»: cada persona como tarjeta de dos filas, sin scroll de lado (25-oct-2026). Sin el modo touch, la tabla de siempre."""
import pathlib
import re


def test_the_cards_only_apply_in_touch_mode_and_the_desktop_table_is_unchanged():
    sp = pathlib.Path("static/js/shared-print.js").read_text(encoding="utf-8")
    rules = [r for r in re.findall(r"'([^']*\{[^']*\})'|\"([^\"]*\{[^\"]*\})\"", sp) for r in r if r and "golden-table" in r]
    assert rules, "no hay reglas de la tarjeta"
    assert all(r.startswith("body.touch-mode") for r in rules), [r for r in rules if not r.startswith("body.touch-mode")]   # nada cambia sin el modo touch
    css = " ".join(rules)
    assert "thead{display:none}" in css and "tr{display:flex;flex-wrap:wrap" in css                       # dos filas, sin columnas que obliguen a desplazarse de lado
    assert "td.action-cell{order:10;flex-basis:100%" in css                                                 # fila 2: los botones
    assert "td[data-field=first_name]" in css and "font-size:1.35rem" in css                                # fila 1: el nombre, grande
    assert "min-height:56px" in css and "word-break:keep-all" in css                                         # botones grandes, sin partir palabras
    style = pathlib.Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".golden-table td.touch-only { display: none; }" in style                                         # la empresa no aparece en la tabla de escritorio


def test_each_directory_cell_says_what_it_is_and_the_buttons_keep_their_behaviour():
    js = pathlib.Path("static/js/directory.js").read_text(encoding="utf-8")
    assert "td.dataset.field = field;" in js and "statusTd.dataset.field = 'status';" in js and "entityTd.className = 'touch-only';" in js
    assert "rowAccredit(user, acc)" in js and "BadgePrint.openPrintWindow(user.id)" in js and "buildEditModal(user)" in js        # los mismos botones, la misma acción
