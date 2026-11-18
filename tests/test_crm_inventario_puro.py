"""CRM → inventario: partes puras (sin base). 2 registros × (1 computador + 1 lector) = 2 + 2; diferencias; asignado sin pisar lo manual antiguo."""
from app import crm_inventory as ci


def test_cantidad_entera_redondea_hacia_arriba():
    assert ci.whole_qty("2") == 2 and ci.whole_qty("1.2") == 2 and ci.whole_qty(0) == 0 and ci.whole_qty(-3) == 0 and ci.whole_qty(None) == 0


def test_agrupa_y_suma_repetidos_e_ignora_texto_libre():
    g = ci.group_products([{"crm_product_id": 1, "name": "Registro", "qty": 1}, {"crm_product_id": 1, "name": "Registro", "qty": 2}, {"crm_product_id": None, "name": "Texto", "qty": 5}, {"crm_product_id": 2, "name": "X", "qty": 0}])
    assert g == {1: {"name": "Registro", "qty": 3}}


def test_implica_categorias_por_cantidad():
    out = ci.implied_totals({10: 2, 11: 1}, {10: [("portatiles", 1), ("lectores", 1)], 11: [("portatiles", 3)]})
    assert out == {"portatiles": 5, "lectores": 2}


def test_categorias_son_las_filas_del_checklist():
    keys = [o["key"] for o in ci.category_options()]
    assert len(keys) == 9 and "portatiles" in keys and "radios" in keys and "lectores" in keys
    labels = {o["key"]: o["label"] for o in ci.category_options()}
    assert labels["monitores_semaforos"] == "Monitores - Semaforos" and labels["radios"].startswith("RADIOS")


def test_requerido_contra_asignado_por_categoria():
    r = {x["key"]: x for x in ci.requirements({"portatiles": 4, "lectores": 2}, {"portatiles": 1, "radios": 3})}
    assert r["portatiles"]["missing"] == 3 and r["lectores"]["missing"] == 2 and r["radios"]["needed"] == 0 and r["radios"]["missing"] == 0
    assert ci.requirements({"lectores": 1}, {"lectores": 5})[0]["missing"] == 0


def test_producto_sin_elementos_declarados_no_implica_nada():
    assert ci.implied_totals({10: 4}, {}) == {}


def test_diferencias_agregado_quitado_cambiado():
    before = {1: {"name": "A", "qty": 2}, 2: {"name": "B", "qty": 1}, 3: {"name": "C", "qty": 4}}
    after = {1: {"name": "A", "qty": 2}, 2: {"name": "B", "qty": 3}, 4: {"name": "D", "qty": 1}}
    d = {x["crm_product_id"]: x for x in ci.diff_products(before, after)}
    assert set(d) == {2, 3, 4} and d[2]["kind"] == "changed" and d[3]["kind"] == "removed" and d[4]["kind"] == "added"
    assert (d[2]["before"], d[2]["after"]) == (1, 3)


def test_sin_diferencias_no_hay_alerta():
    a = {1: {"name": "A", "qty": 2}}
    assert ci.diff_products(a, dict(a)) == []


def test_hash_estable_y_distinto_si_cambia_la_cantidad():
    a, b = {1: {"name": "A", "qty": 2}}, {1: {"name": "Otro nombre", "qty": 2}}
    assert ci.snap_hash(a) == ci.snap_hash(b)
    assert ci.snap_hash(a) != ci.snap_hash({1: {"name": "A", "qty": 3}})


# ------------------------------------------------------------------ reglas de código (sin base)
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _src(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_migracion_0153_encadenada_y_con_id_corto():
    m = _src("alembic/versions/0153_crm_implica_inventario.py")
    assert 'revision = "0153_crm_implica_inventario"' in m and len("0153_crm_implica_inventario") <= 32
    assert 'down_revision = "0152_almacen_novedades"' in m
    for table in ("event_crm_products", "event_crm_sync", "event_inventory_alerts"):
        assert f'"{table}"' in m and f"__tablename__ = '{table}'" in _src("app/models.py")
    n = _src("alembic/versions/0154_crm_implica_categorias.py")
    assert 'revision = "0154_crm_implica_categorias"' in n and 'down_revision = "0153_crm_implica_inventario"' in n and len("0154_crm_implica_categorias") <= 32
    assert "__tablename__ = 'crm_product_categories'" in _src("app/models.py") and "CrmProductInventory" not in _src("app/models.py")


def test_endpoints_sincronos_y_router_registrado():
    r = _src("app/routers/crm_inventory.py")
    assert "async def" not in r
    assert "crm_inventory_router.router" in _src("app/main.py")


def test_ganar_la_oportunidad_captura_la_ultima_cotizacion():
    w = _src("app/crm/won.py")
    assert "crm_inventory.capture_at_win(db, staff, o, event)" in w


def test_la_asignacion_de_equipos_sigue_siendo_de_almacen_y_el_crm_solo_pide_por_categoria():
    inv = _src("app/routers/inventory.py")
    assert "manual_assign_allowed" not in inv and "crm_inventory" not in inv          # Almacén asigna equipos concretos como siempre
    assert "sync_inventory" not in _src("app/crm_inventory.py")


def test_sin_colores_sueltos_ni_onclick_en_el_bloque_nuevo():
    js = _src("static/js/event-inventory-plan.js")
    assert "onclick" not in js and "alert(" not in js.replace("showToast", "")


def test_historial_de_cotizaciones_visible_con_anotacion_y_pdf():
    r = _src("app/routers/crm_quotes.py")
    assert '"/opportunities/{opportunity_id}/quotes"' in r and '"is_last"' in r
    opp = _src("static/js/crm_oportunidad.js")
    assert "/api/crm/opportunities/" in opp and "Descargar PDF" in opp and "Anotación" in opp and "loadQuotes();" in opp
    assert 'id="opQuotes"' in _src("templates/crm_oportunidad.html")
    cot = _src("static/js/crm_cotizacion.js")
    assert "v.meeting_notes" in cot and '"/api/crm/quotes/" + v.id + "/pdf"' in cot
