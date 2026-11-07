"""Campo «inventario» (app/event_inventory.py): validación de líneas y resumen, sin base de datos. Debe coincidir con static/js/gw-inventory.js."""
from app import event_inventory as ei
from app import event_template as et

TYPES = [{"key": "comp", "label": "Computadores", "refs": ["Dell", "HP"]}, {"key": "impr", "label": "Impresoras", "refs": []}]


def _raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ei.InventoryError as exc:
        return str(exc)
    raise AssertionError("debía fallar")


def test_clean_lines_ok_and_free_text():
    out = ei.clean_lines([{"type": "comp", "qty": "2", "ref": "Dell"}, {"type": "impr", "qty": 3, "ref": " Brother QL-800 "}, {"type": "impr", "qty": 1, "ref": ""}], TYPES, "«Inv»")
    assert out == [{"type": "comp", "qty": 2, "ref": "Dell"}, {"type": "impr", "qty": 3, "ref": "Brother QL-800"}, {"type": "impr", "qty": 1, "ref": None}]
    assert ei.clean_lines(None, TYPES, "w") is None and ei.clean_lines([], TYPES, "w") is None


def test_clean_lines_rejects():
    w = "«Inv»"
    assert "desconocido" in _raises(ei.clean_lines, [{"type": "zz", "qty": 1}], TYPES, w)
    assert "desconocido" in _raises(ei.clean_lines, [{"type": ["comp"], "qty": 1}], TYPES, w)
    assert "desconocido" in _raises(ei.clean_lines, ["comp"], TYPES, w)
    for bad in (0, -1, 2.5, "2.5", "dos", None, True, ei.MAX_QTY + 1):
        assert "cantidad" in _raises(ei.clean_lines, [{"type": "impr", "qty": bad}], TYPES, w), bad
    assert "lista" in _raises(ei.clean_lines, [{"type": "comp", "qty": 1, "ref": "Mac"}], TYPES, w)
    assert "lista" in _raises(ei.clean_lines, [{"type": "comp", "qty": 1}], TYPES, w)
    assert "caracteres" in _raises(ei.clean_lines, [{"type": "impr", "qty": 1, "ref": "x" * (ei.MAX_REF_LEN + 1)}], TYPES, w)
    assert "«<»" in _raises(ei.clean_lines, [{"type": "impr", "qty": 1, "ref": "<img src=x>"}], TYPES, w)
    assert "texto" in _raises(ei.clean_lines, [{"type": "impr", "qty": 1, "ref": 5}], TYPES, w)
    assert "repetido" in _raises(ei.clean_lines, [{"type": "impr", "qty": 1, "ref": "Epson"}, {"type": "impr", "qty": 2, "ref": "epson"}], TYPES, w)
    assert "repetido" in _raises(ei.clean_lines, [{"type": "comp", "qty": 1, "ref": "Dell"}, {"type": "comp", "qty": 1, "ref": "Dell"}], TYPES, w)
    assert "líneas" in _raises(ei.clean_lines, [{"type": "impr", "qty": 1, "ref": f"r{i}"} for i in range(ei.MAX_LINES + 1)], TYPES, w)
    assert "lista" in _raises(ei.clean_lines, {"type": "impr"}, TYPES, w)


def test_summary_matches_browser():
    lines = [{"type": "comp", "qty": 2, "ref": "Dell"}, {"type": "impr", "qty": 3, "ref": None}, {"type": "viejo", "qty": 1, "ref": None}]
    assert ei.summary(lines, TYPES) == "Computadores ×2 — Dell; Impresoras ×3; viejo ×1" and ei.summary(None, TYPES) == ""


def test_template_converts_errors_and_keeps_format():
    f = {"key": "c_i", "type": "inventory", "title": "Inv", "config": {"inventory_types": TYPES}}
    assert et.clean_value(f, [{"type": "impr", "qty": 4, "ref": "Epson"}]) == [{"type": "impr", "qty": 4, "ref": "Epson"}]
    try:
        et.clean_value(f, [{"type": "impr", "qty": 0}])
    except et.TemplateError as exc:
        assert "cantidad" in str(exc) and "Inv" in str(exc)
    else:
        raise AssertionError("debía fallar")


def test_designer_types_reject_duplicate_labels():
    try:
        et._clean_inventory_types([{"key": "a", "label": "Impresoras", "refs": []}, {"key": "b", "label": "impresoras", "refs": []}])
    except et.TemplateError as exc:
        assert "llamados" in str(exc)
    else:
        raise AssertionError("debía fallar")
    assert et._clean_inventory_types([{"key": "a", "label": "Impresoras", "refs": ["Brother"]}]) == [{"key": "a", "label": "Impresoras", "refs": ["Brother"]}]
