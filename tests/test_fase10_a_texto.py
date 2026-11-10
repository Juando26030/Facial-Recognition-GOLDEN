"""Fase 10, bloque A: pruebas «de texto» (leen el código fuente; no necesitan base de datos)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_migrations_0122_and_0123_chain_and_columns():
    m122, m123 = read("alembic/versions/0122_dwell_autoscan.py"), read("alembic/versions/0123_item_requires_dwell.py")
    assert 'revision = "0122_dwell_autoscan"' in m122 and 'down_revision = "0121_infra_costs"' in m122
    assert 'revision = "0123_item_requires_dwell"' in m123 and 'down_revision = "0122_dwell_autoscan"' in m123
    assert len("0122_dwell_autoscan") <= 32 and len("0123_item_requires_dwell") <= 32
    models = read("app/models.py")
    for col in ("areas_dwell_enabled", "dwell_prize_enabled", "dwell_reference_minutes", "dwell_threshold_pct", "areas_autoscan", "inventory_autoscan"):
        assert col in m122 and re.search(rf"^\s+{col} = Column", models, re.M), col
    assert "requires_dwell" in m123 and re.search(r"^\s+requires_dwell = Column", models, re.M)
    assert "SET " not in m122.replace("server_default", "") and "advisory" not in m122 + m123


def test_router_is_registered_and_endpoints_are_sync():
    assert "areas_dwell as areas_dwell_router" in read("app/main.py") and "_include(areas_dwell_router.router" in read("app/main.py")
    for rel in ("app/routers/areas_dwell.py", "app/area_dwell_svc.py"):
        assert "async def" not in read(rel), rel
    inv = read("app/routers/inventory.py")
    for route in ('"/inventory/overview"', '"/inventory/calendar"', '"/inventory/products/{product_id}/manage"'):
        assert route in inv
    assert "async def" not in inv


def test_every_dwell_route_has_a_role_and_guards_the_archived_base():
    src = read("app/routers/areas_dwell.py")
    assert src.count("Depends(CONFIG_ROLE)") == src.count("@router."), "toda ruta lleva rol"
    assert "event_archive.require_data_open" in src and 'require_role_excluding("coordinador", ("comercial",))' in src


def test_test_person_never_counts_in_dwell():
    svc = read("app/area_dwell_svc.py")
    assert "testperson.TEST_ID" in svc and "func.upper(AreaMovement.user_id) != testperson.TEST_ID" in svc
    assert "func.upper(EventAttendee.user_id) != testperson.TEST_ID" in read("app/routers/areas_dwell.py")          # nunca se le cambia el certificado


def test_autoscan_and_requires_dwell_are_wired_in_areas_inventory():
    src = read("app/routers/areas_inventory.py")
    assert "not event.auto_register and not event.areas_autoscan and not confirm" in src
    assert "area_dwell_svc.prize_active(event) and not area_dwell_svc.qualifies" in src
    assert '"requires_dwell": bool(item.requires_dwell)' in src and 'data["requires_dwell"]' in src


def test_parametros_has_the_dwell_block_and_item_column():
    html = read("templates/kiosk_parametros.html")
    for needle in ('id="dwellBox"', 'id="dwellEnabled"', 'id="dwellPrize"', 'id="dwellRefH"', 'id="dwellPct"', 'id="areasAutoscan"', 'id="inventoryAutoscan"', 'id="dwellSave"',
                   'id="dwellCerts"', "js/dwell-params.js", "item-dwell", "newItemDwell", "Solo a quien cumple la estadía"):
        assert needle in html, needle
    assert "cols=7" in html and 'colspan="7"' in html
    assert "data-pnodirty" in html.split('id="dwellBox"')[1].split(">")[0]          # módulo propio: fuera del «Sin guardar»


def test_kiosk_pages_know_about_autoscan():
    assert "window.AUTOSCAN" in read("templates/kiosk_inventario.html") and "event.inventory_autoscan" in read("templates/kiosk_inventario.html")
    assert "event.areas_autoscan" in read("templates/kiosk_areas.html")
    js = read("static/js/inventario.js")
    assert "window.AUTOSCAN" in js and "byId(" in js and "if (auto && AUTOSCAN) deliver()" in js and "delivering" in js


def test_inventory_page_shows_the_catalog_and_calendar_not_the_event_list():
    html, js = read("templates/inventario.html"), read("static/js/inventario-page.js")
    assert "invEvents" not in html and "Elige un evento" not in html
    for needle in ('id="invCatalog"', 'id="invPanelCal"', "Dónde está cada equipo", 'data-view="day"', 'data-view="week"', 'data-view="month"', "gw-inventory-calendar.css"):
        assert needle in html, needle
    assert "/api/inventory/events" not in js and "/api/inventory/overview" in js and "/api/inventory/calendar" in js and "/manage" in js
    assert "Abrir inventario del evento" in js


@pytest.mark.parametrize("rel", ["static/js/inventario-page.js", "static/js/dwell-params.js", "static/js/inventario.js"])
def test_new_js_follows_the_frontend_rules(rel):
    js = read(rel)
    assert not re.search(r"(?<![.\w])(alert|confirm|prompt)\(", js), "usar showToast / showConfirm / showPrompt"
    assert "onclick=" not in js and "innerHTML = esc" not in js
    assert "textContent" in js or "esc(" in js


def test_calendar_css_uses_only_tokens():
    css = read("static/css/gw-inventory-calendar.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and "rgb(" not in css
    assert "var(--gw-" in css


def test_templates_still_parse():
    pytest.importorskip("jinja2")
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / "templates")))
    for name in ("inventario.html", "kiosk_parametros.html", "kiosk_inventario.html", "kiosk_areas.html"):
        env.parse(read(f"templates/{name}"))


def test_catalog_is_managed_by_admin_almacen_and_super_admin():
    inv = read("app/routers/inventory.py")
    assert "require_super_admin" not in inv and inv.count("Depends(MANAGER)") >= 11          # 10 rutas del catálogo + manage
    cfg, page = read("templates/configuracion.html"), read("templates/inventario.html")
    assert "_inventory_catalog_admin.html" in cfg and "_inventory_catalog_admin.html" in page and "inv_manager" in page
    assert 'id="invProdForm"' in read("templates/_inventory_catalog_admin.html") and 'id="invProdForm"' not in cfg
    assert '"inv_manager"' in read("app/main.py")


def test_areas_kiosk_shows_the_dwell_statistics():
    html, js = read("templates/kiosk_areas.html"), read("static/js/areas-dwell.js")
    for needle in ('id="dwellPanel"', 'id="adwCalc"', 'id="adwXlsx"', 'id="adwCsv"', 'id="adwCerts"', "js/areas-dwell.js", "areas_dwell_enabled"):
        assert needle in html, needle
    assert "/areas-dwell" in js and "apply-certificates" in js and "export?" in js and "showConfirm" in js


def test_doc_section_exists():
    doc = read("docs/FASE_10_AJUSTES_NOV10.md")
    assert "Bloque A" in doc and "0122" in doc and "0123" in doc
