"""Preimpresiones (18-nov-2026): reglas puras, filtro y comprobaciones estáticas de que la impresión NO cambió."""
import pathlib

from app import preprint

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _match(p, c):                      # imita roulette._match para lo que usan estas pruebas
    if c["field"] == "category":
        return c["value"] in p.get("categories", [])
    if c["field"] == "entity":
        return (c["value"].lower() in p.get("entity", "").lower()) if c.get("op") == "contains" else p.get("entity") == c["value"]
    return True


PEOPLE = [
    {"id": "1", "name": "José Pérez", "entity": "Ministerio", "role": "Director", "categories": ["VIP"], "preprinted_at": None},
    {"id": "2", "name": "Ana Gómez", "entity": "Empresa", "role": "", "categories": ["General"], "preprinted_at": "2026-11-18"},
    {"id": "3", "name": "Luis Ríos", "entity": "Ministerio de Salud", "role": "", "categories": ["VIP"], "preprinted_at": "2026-11-18"},
]


def test_estados():
    assert preprint.can_preprint("creado") and preprint.can_preprint("en_proceso")
    assert not preprint.can_preprint("finalizado") and not preprint.can_preprint(None)


def test_una_sola_ejecucion_con_muchas_hojas():
    assert preprint.MAX_BATCH >= 200


def test_clean_ids():
    assert preprint.clean_ids(["1", " 1 ", "", None, "2"]) == ["1", "2"]
    assert preprint.clean_ids(["a", "b", "c"], limit=2) == ["a", "b"]


def test_busqueda_sin_tildes_y_por_palabras():
    assert preprint.matches_text(PEOPLE[0], "jose perez")
    assert preprint.matches_text(PEOPLE[0], "minist")
    assert not preprint.matches_text(PEOPLE[0], "ana")
    assert preprint.matches_text(PEOPLE[0], "")


def test_filtro_y_campo_preimpresa():
    f = lambda conds: [p["id"] for p in preprint.apply_filter(PEOPLE, {"conditions": conds}, _match)]  # noqa: E731
    assert f([]) == ["1", "2", "3"]
    assert f([{"field": "category", "value": "VIP"}]) == ["1", "3"]
    assert f([{"field": "category", "value": "VIP"}, {"field": "preprinted", "value": "no"}]) == ["1"]
    assert f([{"field": "preprinted", "value": "si"}]) == ["2", "3"]
    assert f([{"field": "entity", "op": "contains", "value": "ministerio"}]) == ["1", "3"]


def test_resumen():
    assert preprint.summarize(PEOPLE) == {"total": 3, "preprinted": 2, "pending": 1}


def test_ventana_de_impresion_sin_cambios_de_formato():
    html = (ROOT / "templates" / "badge_print.html").read_text(encoding="utf-8")
    assert "62" in html and "99.8" in html and "PAGE_LEFT_MM = 0.5" in html and "MAX_IMG_H = 96" in html
    assert "kiosk-printing" not in html


def test_pantalla_imprime_en_una_sola_ventana():
    js = (ROOT / "static" / "js" / "preprint.js").read_text(encoding="utf-8")
    assert js.count("window.open(") == 1 and "goldenweb_print" in js and "users=" in js and "preprint=1" in js
    assert "alert(" not in js.replace("showConfirm", "") and "confirm(" not in js.replace("showConfirm", "")
    assert "kiosk-printing" not in js


def test_mosaico_en_el_kiosco():
    t = (ROOT / "templates" / "kiosk_select.html").read_text(encoding="utf-8")
    assert "/preimpresiones" in t


def test_hojas_multiples_no_se_parten_con_un_papel_mas_corto():
    html = (ROOT / "templates" / "badge_print.html").read_text(encoding="utf-8")
    assert "height:min(calc(${pageH}mm - 0.2mm), 100vh)" in html          # con un papel de 89 mm salían 4 hojas (2 en blanco) para 2 escarapelas
    assert "const PAGE_W = 62, PAGE_LEFT_MM = 0.5, PAGE_H = 99.8, MAX_IMG_H = 96;" in html


def test_estado_de_registro_va_primero():
    ppl = [{"id": "1", "status": "registrado"}, {"id": "2", "status": "no_registrado"}, {"id": "3"}]
    assert [p["id"] for p in preprint.by_registration(ppl, "si")] == ["1"]
    assert [p["id"] for p in preprint.by_registration(ppl, "no")] == ["2", "3"]
    assert len(preprint.by_registration(ppl, "todos")) == 3
    assert len(preprint.by_registration(ppl, "cualquiera")) == 3


def test_la_impresion_normal_de_una_escarapela_tampoco_deja_hoja_en_blanco():
    """19-nov-2026: la ventana de UNA escarapela usa el mismo tope de alto (100vh) y sin salto de página final que las hojas múltiples; las medidas inamovibles no cambian."""
    html = (ROOT / "templates" / "badge_print.html").read_text(encoding="utf-8")
    assert html.count("height:min(calc(${pageH}mm - 0.2mm), 100vh)") >= 2
    assert "break-after:avoid; page-break-after:avoid" in html and "body { overflow:hidden; }" in html
    assert "const PAGE_W = 62, PAGE_LEFT_MM = 0.5, PAGE_H = 99.8, MAX_IMG_H = 96;" in html
