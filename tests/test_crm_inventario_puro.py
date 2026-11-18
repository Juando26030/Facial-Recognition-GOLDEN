"""CRM → inventario: partes puras (sin base). 2 registros × (1 computador + 1 lector) = 2 + 2; diferencias; asignado sin pisar lo manual antiguo."""
from app import crm_inventory as ci


def test_cantidad_entera_redondea_hacia_arriba():
    assert ci.whole_qty("2") == 2 and ci.whole_qty("1.2") == 2 and ci.whole_qty(0) == 0 and ci.whole_qty(-3) == 0 and ci.whole_qty(None) == 0


def test_agrupa_y_suma_repetidos_e_ignora_texto_libre():
    g = ci.group_products([{"crm_product_id": 1, "name": "Registro", "qty": 1}, {"crm_product_id": 1, "name": "Registro", "qty": 2}, {"crm_product_id": None, "name": "Texto", "qty": 5}, {"crm_product_id": 2, "name": "X", "qty": 0}])
    assert g == {1: {"name": "Registro", "qty": 3}}


def test_implica_cantidad_por_unidades():
    out = ci.implied_totals({10: 2, 11: 1}, {10: [(100, 1), (101, 1)], 11: [(100, 3)]})
    assert out == {100: 5, 101: 2}


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


def test_delta_conserva_lo_manual_y_no_baja_de_lo_que_salio():
    assert ci.apply_delta(assigned=7, old_implied=2, new_implied=4) == 9          # 5 manuales + 4 del CRM
    assert ci.apply_delta(assigned=2, old_implied=2, new_implied=0) == 0
    assert ci.apply_delta(assigned=4, old_implied=4, new_implied=1, out=3) == 3          # ya salieron 3: no baja de ahí


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
    for table in ("crm_product_inventory", "event_crm_products", "event_crm_sync", "event_inventory_alerts"):
        assert f'"{table}"' in m and f"__tablename__ = '{table}'" in _src("app/models.py")


def test_endpoints_sincronos_y_router_registrado():
    r = _src("app/routers/crm_inventory.py")
    assert "async def" not in r
    assert "crm_inventory_router.router" in _src("app/main.py")


def test_ganar_la_oportunidad_captura_la_ultima_cotizacion():
    w = _src("app/crm/won.py")
    assert "crm_inventory.capture_at_win(db, staff, o, event)" in w


def test_el_plan_marca_lo_que_viene_del_crm_y_las_asignaciones_a_mano_se_bloquean():
    inv = _src("app/routers/inventory.py")
    assert "manual_assign_allowed" in inv and inv.count("manual_assign_allowed") >= 2          # put_plan y /inventory/assign
    assert '"from_crm"' in inv and '"manual_ok"' in inv


def test_sin_colores_sueltos_ni_onclick_en_el_bloque_nuevo():
    js = _src("static/js/event-inventory-plan.js")
    assert "onclick" not in js and "alert(" not in js.replace("showToast", "")
