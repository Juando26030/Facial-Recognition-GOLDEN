"""Hotfix 23-nov-2026 (sin base de datos): el panel de Estadísticas y Parámetros › Campos traen el alcance (toda la base / registrados / no registrados)
y las barras de categorías salen de un color por categoría."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_panel_scope_selector_is_temporary_and_starts_from_config():
    js = read("static/js/stats-event.js")
    assert "chart-scope-select" in js and "'&scope='" in js
    assert "addVariableChart(v.key, v.label, v.default_chart_type, v.default_stat_scope)" in js          # al abrir manda lo configurado
    assert "localStorage" not in js and "sessionStorage" not in js                                         # el cambio en pantalla no se guarda
    assert "/^(zona|inv):/" in js                                                                          # zonas e inventario no llevan selector


def test_category_bars_are_multicolor_in_panel():
    js = read("static/js/stats-event.js")
    assert "color: dataType !== 'numeric' ? list.map(" in js
    assert "backgroundColor: o.color || palette()[0]" in read("static/js/analytics-dashboard.js")          # rowBars acepta una lista de colores


def test_parametros_has_scope_selector_and_sends_it():
    html = read("templates/kiosk_parametros.html")
    assert "cfg-stat-scope" in html and "STAT_SCOPE_OPTIONS" in html
    assert "default_stat_scope: statEnabled ? tr.querySelector('.cfg-stat-scope').value : 'all'" in html
    for label in ("Toda la base", "Solo registrados", "Solo no registrados"):
        assert label in html


def test_backend_scope_rules():
    stats, par = read("app/routers/stats.py"), read("app/routers/parametros.py")
    assert 'STAT_SCOPES = ("all", "registered", "unregistered")' in par
    assert "def split_chart_scope" in par and "def join_chart_scope" in par
    assert "registered_ids(db, event.id)" in stats and "scope_users(users, registered, scope)" in stats
    assert 'AccessLog.record_type != "Actualizado"' in stats                                               # misma regla de «registrado» que el reporte
    assert '"default_stat_scope"' in stats
