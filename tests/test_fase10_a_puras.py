"""Fase 10, bloque A (10-nov-2026): lógica pura de permanencia en zonas y del calendario de inventario. No necesita base de datos."""
from datetime import date, datetime as D

import pytest

from app import area_dwell as dw
from app import inventory_calendar as ic


def mv(uid, area, d, h, m):
    return dw.Move(uid, area, d, D(2026, 11, 10, h, m))


# ---------------------------------------------------------------- permanencia
def test_entries_and_exits_add_up_ten_plus_five_is_fifteen():
    moves = [mv("1", 1, "in", 10, 0), mv("1", 1, "out", 10, 10), mv("1", 1, "in", 11, 0), mv("1", 1, "out", 11, 5)]
    d = dw.compute(moves, D(2026, 11, 10, 23, 0))["1"]
    assert d.seconds == 15 * 60 and d.entries == 2 and not d.open


def test_open_entry_counts_until_the_cap_and_is_flagged():
    d = dw.compute([mv("1", 1, "in", 10, 0)], D(2026, 11, 10, 12, 0))["1"]
    assert d.seconds == 2 * 3600 and d.open
    assert dw.compute([mv("1", 1, "in", 10, 0)], None)["1"].seconds == 0          # sin límite: queda marcada pero no suma


def test_duplicate_in_and_orphan_out_do_not_add():
    moves = [mv("1", 1, "out", 9, 0), mv("1", 1, "in", 10, 0), mv("1", 1, "in", 10, 30), mv("1", 1, "out", 11, 0)]
    assert dw.compute(moves, D(2026, 11, 10, 23, 0))["1"].seconds == 3600


def test_overlapping_areas_are_counted_once():
    moves = [mv("1", 1, "in", 10, 0), mv("1", 2, "in", 10, 30), mv("1", 1, "out", 11, 0), mv("1", 2, "out", 12, 0)]
    assert dw.compute(moves, D(2026, 11, 10, 23, 0))["1"].seconds == 2 * 3600          # 10:00-12:00, no 2 h 30


def test_people_are_independent_and_unsorted_input_is_ok():
    moves = [mv("2", 1, "out", 10, 20), mv("1", 1, "out", 10, 10), mv("2", 1, "in", 10, 0), mv("1", 1, "in", 10, 0)]
    r = dw.compute(moves, None)
    assert r["1"].seconds == 600 and r["2"].seconds == 1200


def test_percent_threshold_and_exact_comparison():
    assert dw.percent(900, 18) == 83.3 and dw.percent(900, None) is None
    # 24 h de referencia y 80 %: 19 h 12 min exactos cumplen; un segundo menos no
    ref = 24 * 60
    need = int(0.8 * ref * 60)
    assert dw.meets(need, ref, 80) and not dw.meets(need - 1, ref, 80)
    assert not dw.meets(10 ** 6, None, 80)


def test_summarize_counts_each_step_and_open_entries():
    rows = [{"seconds": 24 * 3600, "open": False}, {"seconds": 12 * 3600, "open": True}, {"seconds": 3600, "open": False}]
    s = dw.summarize(rows, 24 * 60, 50)
    assert s["people"] == 3 and s["qualifying"] == 2 and s["steps"]["100"] == 1 and s["steps"]["50"] == 2 and s["with_open_entry"] == 1


def test_reference_falls_back_to_the_event_duration():
    win = dw.event_window_local(date(2026, 11, 10), date(2026, 11, 11), "08:00", "08:00")
    assert dw.window_minutes(win) == 24 * 60
    assert dw.reference_for(None, win) == 24 * 60 and dw.reference_for(600, win) == 600
    assert dw.event_window_local(None, None, None, None) is None
    assert dw.reference_for(None, None) is None
    one_day = dw.event_window_local(date(2026, 11, 10), None, None, None)
    assert dw.window_minutes(one_day) == 24 * 60 - 1


@pytest.mark.parametrize("raw,ok", [("", True), (None, True), ("90", True), (0, False), ("x", False), (-5, False), (10 ** 9, False)])
def test_reference_validation(raw, ok):
    if ok:
        dw.clean_reference_minutes(raw)
    else:
        with pytest.raises(dw.DwellError):
            dw.clean_reference_minutes(raw)


@pytest.mark.parametrize("raw,expected", [("", 80), (None, 80), ("65", 65), (100, 100)])
def test_threshold_defaults_and_bounds(raw, expected):
    assert dw.clean_threshold_pct(raw) == expected
    for bad in (0, 101, "abc"):
        with pytest.raises(dw.DwellError):
            dw.clean_threshold_pct(bad)


def test_format_minutes_and_cap():
    assert dw.format_minutes(125 * 60) == "2 h 05 min" and dw.format_minutes(45 * 60) == "45 min" and dw.format_minutes(0) == "0 min"
    now = D(2026, 11, 10, 12, 0)
    assert dw.cap_for(D(2026, 11, 10, 9, 0), now) == D(2026, 11, 10, 9, 0)          # el evento ya terminó
    assert dw.cap_for(D(2026, 11, 11, 9, 0), now) == now                              # aún no termina: hasta ahora
    assert dw.cap_for(None, now) == now


# ---------------------------------------------------------------- calendario de inventario
def test_event_span_includes_setup_and_handles_missing_dates():
    assert ic.event_span(None, None) is None
    assert ic.event_span(date(2026, 11, 10), None) == (date(2026, 11, 10), date(2026, 11, 10))
    assert ic.event_span(date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 8)) == (date(2026, 11, 8), date(2026, 11, 12))
    assert ic.event_span(date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 11)) == (date(2026, 11, 10), date(2026, 11, 12))


def test_usage_and_availability_by_day():
    events = [{"span": (date(2026, 11, 10), date(2026, 11, 12)), "lines": {1: 5, 2: 1}}, {"span": (date(2026, 11, 12), date(2026, 11, 13)), "lines": {1: 4}}]
    assert ic.usage_on(date(2026, 11, 11), events) == {1: 5, 2: 1}
    assert ic.usage_on(date(2026, 11, 12), events) == {1: 9, 2: 1}
    assert ic.usage_on(date(2026, 11, 14), events) == {}
    assert ic.available(10, 9) == 1 and ic.available(8, 9) == -1 and ic.available(None, 9) is None


def test_range_validation():
    assert ic.clean_range("2026-11-01", "2026-11-30") == (date(2026, 11, 1), date(2026, 11, 30))
    for a, b in (("x", "2026-11-01"), ("2026-11-05", "2026-11-01"), ("2026-01-01", "2026-12-31")):
        with pytest.raises(ic.RangeError):
            ic.clean_range(a, b)
    assert len(ic.days_between(date(2026, 11, 1), date(2026, 11, 7))) == 7
    assert ic.pending_return(5, 2, 1) == 2 and ic.pending_return(5, 5, 1) == 0
