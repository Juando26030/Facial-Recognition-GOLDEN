"""Almacén · Pieza 3 (lógica pura): novedades y bloqueo. No necesita base de datos."""
import pytest

from app import almacen_moves as m, almacen_novelties as n


def test_text_is_required_trimmed_and_limited():
    assert n.clean_text("  se   rompió el  cable ", "Qué pasó") == "se rompió el cable"
    for bad in (None, "", "  ", "ab"):
        with pytest.raises(n.NoveltyError):
            n.clean_text(bad, "Qué pasó")
    with pytest.raises(n.NoveltyError):
        n.clean_text("x" * (n.MAX_TEXT + 1), "Qué pasó")


def test_quantity_must_be_a_positive_integer():
    assert n.clean_qty(None) == 1 and n.clean_qty("3") == 3
    for bad in ("0", "-1", "abc", "1.5", n.MAX_QTY + 1):
        with pytest.raises(n.NoveltyError):
            n.clean_qty(bad)


def test_available_subtracts_open_novelties_and_never_goes_negative():
    assert n.available(10, 3) == 7 and n.available(2, 5) == 0 and n.available(None, 4) is None


def test_serial_unit_in_bodega_becomes_novedad_and_one_in_an_event_keeps_its_status():
    assert n.plan_open(tracking="serial", consumable=False, unit_status="disponible").unit_status == "novedad"
    assert n.plan_open(tracking="serial", consumable=False, unit_status="en_evento").unit_status is None


def test_serial_unit_with_open_novelty_or_odd_status_is_refused():
    with pytest.raises(n.NoveltyError, match="ya tiene una novedad"):
        n.plan_open(tracking="serial", consumable=False, unit_status="novedad")
    with pytest.raises(n.NoveltyError):
        n.plan_open(tracking="serial", consumable=False, unit_status="baja")


def test_consumables_do_not_carry_novelties():
    with pytest.raises(n.NoveltyError, match="consumible"):
        n.plan_open(tracking="cantidad", consumable=True, unit_status=None, product_name="Cinta")


def test_quantity_novelty_cannot_exceed_stock():
    p = n.plan_open(tracking="cantidad", consumable=False, unit_status=None, qty=2, open_qty=1, stock=5)
    assert p.qty == 2 and p.unit_status is None
    with pytest.raises(n.NoveltyError):
        n.plan_open(tracking="cantidad", consumable=False, unit_status=None, qty=5, open_qty=1, stock=5)


def test_entry_novelty_quantity():
    assert n.entry_novelty_qty(tracking="serial", entry_qty=1) == 1
    assert n.entry_novelty_qty(tracking="cantidad", entry_qty=4) == 1
    assert n.entry_novelty_qty(tracking="cantidad", entry_qty=4, qty=3) == 3
    with pytest.raises(n.NoveltyError):
        n.entry_novelty_qty(tracking="cantidad", entry_qty=2, qty=3)


def test_resolve_returns_the_unit_to_disponible_once():
    assert n.plan_resolve(resolved=False, unit_status="novedad") == "disponible"
    assert n.plan_resolve(resolved=False, unit_status="en_evento") is None
    assert n.plan_resolve(resolved=False, unit_status=None) is None
    with pytest.raises(n.NoveltyError):
        n.plan_resolve(resolved=True, unit_status="disponible")


def test_exit_of_a_unit_in_novelty_is_blocked_with_its_text():
    with pytest.raises(m.MoveError, match="novedad"):
        m.plan_exit(tracking="serial", consumable=False, assigned=1, out=0, qty=1, unit_status="novedad", novelty_text="pantalla rota")
