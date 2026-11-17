"""Almacén · Pieza 2 (lógica pura): reglas de salida, entrada, anulación, alistado, tablero y fotos. No necesita base de datos."""
import io

import pytest
from PIL import Image

from app import almacen, almacen_moves as m, almacen_photos


def exit_(**kw):
    base = dict(tracking="cantidad", consumable=False, assigned=10, out=0, qty=1)
    base.update(kw)
    return m.plan_exit(**base)


def test_a_normal_exit_inside_what_the_event_asked_needs_no_reason():
    p = exit_(assigned=10, out=4, qty=6)
    assert (p.out_add, p.extra, p.consumed_add, p.reason, p.plan_b) == (6, 0, 0, None, False)


def test_exceeding_the_assigned_quantity_asks_for_a_reason_or_plan_b():
    with pytest.raises(m.MoveError) as e:
        exit_(assigned=10, out=9, qty=3, product_name="Cable USB")
    assert e.value.needs_reason and e.value.extra == 2 and "Ajusta primero" in str(e.value)
    p = exit_(assigned=10, out=9, qty=3, reason="  El cliente pidió dos más  ")
    assert p.extra == 2 and p.reason == "El cliente pidió dos más" and not p.plan_b
    p = exit_(assigned=10, out=9, qty=3, plan_b=True)
    assert p.extra == 2 and p.plan_b and p.reason is None


def test_a_product_the_event_never_asked_for_needs_justification_too():
    with pytest.raises(m.MoveError) as e:
        exit_(assigned=0, out=0, qty=1, product_name="Pulpos")
    assert e.value.needs_reason and "no pidió" in str(e.value)


def test_reason_and_plan_b_are_ignored_when_nothing_exceeds():
    p = exit_(assigned=5, out=0, qty=2, reason="no hace falta", plan_b=True)
    assert p.extra == 0 and p.reason is None and not p.plan_b


def test_a_serial_unit_leaves_only_if_it_is_available():
    assert exit_(tracking="serial", unit_status="disponible").out_add == 1
    with pytest.raises(m.MoveError, match="ya está en el evento «Feria»"):
        exit_(tracking="serial", unit_status="en_evento", unit_event_name="Feria")
    with pytest.raises(m.MoveError, match="novedad"):
        exit_(tracking="serial", unit_status="novedad")
    with pytest.raises(m.MoveError, match="de a uno"):
        exit_(tracking="serial", unit_status="disponible", qty=2)


def test_a_consumable_that_leaves_counts_as_consumed_right_away():
    p = exit_(consumable=True, assigned=10, qty=4)
    assert (p.out_add, p.consumed_add) == (4, 4)


def test_entries_only_for_what_is_pending_and_never_for_consumables():
    assert m.plan_entry(tracking="cantidad", consumable=False, out=10, returned=4, consumed=0, qty=6) == 6
    with pytest.raises(m.MoveError, match="Solo faltan 6"):
        m.plan_entry(tracking="cantidad", consumable=False, out=10, returned=4, consumed=0, qty=7, product_name="Cable")
    with pytest.raises(m.MoveError, match="nada pendiente"):
        m.plan_entry(tracking="cantidad", consumable=False, out=3, returned=3, consumed=0, qty=1)
    with pytest.raises(m.MoveError, match="consumible"):
        m.plan_entry(tracking="cantidad", consumable=True, out=3, returned=0, consumed=3, qty=1)


def test_a_serial_unit_can_only_come_back_if_it_is_out():
    assert m.plan_entry(tracking="serial", consumable=False, out=1, returned=0, consumed=0, qty=1, unit_status="en_evento") == 1
    with pytest.raises(m.MoveError, match="ya está en bodega"):
        m.plan_entry(tracking="serial", consumable=False, out=1, returned=1, consumed=0, qty=1, unit_status="disponible")


def test_event_state_decides_where_material_can_move():
    m.check_event("creado", False, "salida")
    m.check_event("en_proceso", False, "salida")
    m.check_event("finalizado", False, "entrada")
    with pytest.raises(m.MoveError):
        m.check_event("finalizado", False, "salida")
    with pytest.raises(m.MoveError, match="archivado"):
        m.check_event("creado", True, "entrada")


def test_undo_reverses_counters_and_needs_the_last_movement():
    u = m.plan_undo(kind="salida", qty=3, extra=2, consumable=True, voided=False, has_later=False)
    assert (u.out_sub, u.consumed_sub, u.returned_sub, u.assigned_sub) == (3, 3, 0, 2)
    u = m.plan_undo(kind="entrada", qty=1, extra=0, consumable=False, voided=False, has_later=False)
    assert (u.out_sub, u.returned_sub) == (0, 1)
    with pytest.raises(m.MoveError, match="posterior"):
        m.plan_undo(kind="salida", qty=1, extra=0, consumable=False, voided=False, has_later=True)
    with pytest.raises(m.MoveError, match="anulado"):
        m.plan_undo(kind="salida", qty=1, extra=0, consumable=False, voided=True, has_later=False)


def test_quantities_and_texts_are_cleaned():
    assert m.clean_move_qty("") == 1 and m.clean_move_qty(" 7 ") == 7
    for bad in (0, -1, "x", True, 2_000_000):
        with pytest.raises(m.MoveError):
            m.clean_move_qty(bad)
    with pytest.raises(m.MoveError):
        m.clean_text("a" * 301, 300, "La razón")
    assert m.clean_text("  hola   mundo ", 300, "x") == "hola mundo" and m.clean_text("   ", 300, "x") is None
    with pytest.raises(m.MoveError):
        m.clean_text("<script>", 300, "x")


def test_check_updates_accept_only_known_rows_and_valid_values():
    assert m.clean_row_key("portatiles") == "portatiles" and m.clean_row_key("plan_b") == "plan_b"
    with pytest.raises(m.MoveError):
        m.clean_row_key("no_existe")
    assert m.clean_check_update({"done": True, "notes": " ok "}) == {"done": True, "notes": "ok"}
    for bad in ({}, {"done": "si"}, {"done": 1}):
        with pytest.raises(m.MoveError):
            m.clean_check_update(bad)


def test_the_board_has_the_43_rows_and_extras_do_not_count_as_needed():
    lines = [{"row_key": "portatiles", "assigned": 12, "out": 12, "returned": 5, "consumed": 0, "extra": 2, "plan_b": True},
             {"row_key": "portatiles", "assigned": 3, "out": 3, "returned": 3, "consumed": 0, "extra": 0},
             {"row_key": "cinta_gaffer", "assigned": 4, "out": 4, "returned": 0, "consumed": 4, "extra": 0},
             {"row_key": None, "assigned": 9, "out": 9, "returned": 0, "consumed": 0, "extra": 0}]
    board = m.build_board(lines, {"portatiles": {"done": True, "notes": "revisados"}, "plan_b": {"done": True, "notes": None}})
    assert len(board) == 43
    p = next(r for r in board if r["key"] == "portatiles")
    assert (p["needed"], p["out"], p["returned"], p["pending"], p["extra"], p["plan_b"], p["done"], p["notes"]) == (13, 15, 8, 7, 2, True, True, "revisados")
    g = next(r for r in board if r["key"] == "cinta_gaffer")
    assert (g["needed"], g["out"], g["pending"]) == (4, 4, 0)
    manual = next(r for r in board if r["key"] == "plan_b")
    assert manual["kind"] == "manual" and manual["needed"] is None and manual["done"] is True
    s = m.board_summary(board)
    assert s["rows"] == 43 and s["done"] == 2 and s["pending_return"] == 7 and s["extras"] == 2


def test_an_empty_event_gives_a_board_with_zeros():
    board = m.build_board([], {})
    inv = [r for r in board if r["kind"] == "inv"]
    assert len(inv) == len(almacen.inventory_row_keys()) == 38 and all(r["needed"] == 0 and r["pending"] == 0 for r in inv)


def _img(fmt="PNG", size=(3000, 2000), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30) if mode == "RGB" else (200, 30, 30, 120)).save(buf, format=fmt)
    return buf.getvalue()


def test_photos_are_shrunk_and_re_encoded_as_jpeg():
    out = almacen_photos.process_photo(_img("PNG"), "equipo.png")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and max(im.size) == almacen_photos.MAX_SIDE
    out = almacen_photos.process_photo(_img("PNG", (200, 100), "RGBA"), "logo.png")
    assert Image.open(io.BytesIO(out)).format == "JPEG"


def test_photos_reject_wrong_formats_and_disguised_files():
    with pytest.raises(almacen.AlmacenError, match="JPG"):
        almacen_photos.process_photo(_img("PNG"), "equipo.svg")
    with pytest.raises(almacen.AlmacenError):
        almacen_photos.process_photo(b"esto no es una imagen", "equipo.jpg")
    with pytest.raises(almacen.AlmacenError, match="realmente"):
        almacen_photos.process_photo(_img("PNG", (50, 50)), "equipo.jpg")
    with pytest.raises(almacen.AlmacenError):
        almacen_photos.process_photo(b"", "equipo.jpg")
