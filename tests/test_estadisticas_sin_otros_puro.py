"""Hotfix 24-nov-2026 (sin base de datos): ninguna variable de estadísticas agrupa categorías en «Otros»."""
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_event_stats_and_form_stats_do_not_cap_categories():
    stats, fstats = read("app/routers/stats.py"), read("app/form_stats.py")
    assert "_MAX_CATEGORIES" not in stats and '"Otros"' not in stats
    assert "MAX_ITEMS" not in fstats and "Otros (" not in fstats


def test_excel_charts_list_every_category_and_tall_bars_grow():
    from app import report_charts as rc            # openpyxl está instalado donde corre el CI; aquí solo si existe
    cats, vals = rc.top_with_others(Counter({f"c{i}": i + 1 for i in range(40)}))
    assert len(cats) == 40 and "Otros" not in cats and vals[0] == 40
    spec = {"kind": "barh", "cats": cats}
    assert rc.is_tall(spec) and rc.chart_height(spec) > rc.CHART_H and rc.chart_height(spec) <= 60
    assert not rc.is_tall({"kind": "barh", "cats": cats[:8]}) and not rc.is_tall({"kind": "doughnut", "cats": cats})


def test_panel_canvas_grows_with_every_category():
    js = read("static/js/analytics-dashboard.js")
    assert "Math.min(1600" not in js and "Math.min(1000" not in js                  # antes: tope fijo, las filas se encimaban con muchas empresas
    assert "const MAX_CANVAS_PX = 30000;" in js and "devicePixelRatio: GWViz.fitDpr(plan.height)" in js


def test_excel_chart_title_does_not_overlap_the_plot():
    src = read("app/report_charts.py")
    assert "ch.title.overlay = False" in src and "ManualLayout(" in src and "TITLE_CM" in src
