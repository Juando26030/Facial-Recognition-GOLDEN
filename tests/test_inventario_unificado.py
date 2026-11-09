"""Fase 5 · unificación de los dos inventarios (9-nov-2026): el campo «Inventario» de la plantilla pasa al catálogo sin perder ni pisar nada (app/inventory_unify.py, migración 0109)."""
import json
from pathlib import Path

from app import inventory_unify as iu
from app.models import Event, EventInventoryItem, EventTemplate, InventoryCategory, InventoryProduct

SRC = Path(__file__).resolve().parent.parent
TYPES = [{"key": "pa", "label": "Pañoletas", "refs": ["Roja", "Azul"]}, {"key": "cu", "label": "Cuerdas", "refs": []}]


def _template(db, retired=False):
    fields = [{"key": "name", "type": "text", "title": "Nombre", "required": True, "options": [], "config": {}, "help": "", "retired": False},
              {"key": "c_inv", "type": "inventory", "title": "Inventario", "required": True, "options": [], "config": {"inventory_types": TYPES}, "help": "", "retired": retired}]
    db.add(EventTemplate(scope="global", fields_json=json.dumps(fields), creation_layout_json="{}", calendar_layout_json="{}"))
    db.commit()


def _run(db):
    stats = iu.migrate(db.connection())
    db.commit()
    db.expire_all()
    return stats


def test_pure_aggregation():
    lines = [{"type": "pa", "qty": 5, "ref": "Roja"}, {"type": "pa", "qty": "3", "ref": "Azul"}, {"type": "pa", "qty": 2, "ref": "Roja"}, {"type": "cu", "qty": 4}, {"type": "x", "qty": 0}, "basura"]
    got = iu.aggregate_lines(lines, {"pa": "Pañoletas", "cu": "Cuerdas"})
    assert got == {"Pañoletas": {"qty": 10, "refs": ["Roja", "Azul"]}, "Cuerdas": {"qty": 4, "refs": []}}
    assert iu.aggregate_lines(None, {}) == {} and iu.inventory_field_keys([{"key": "a", "type": "inventory"}, {"key": "b", "type": "text"}]) == ["a"]
    assert iu._notes([]) is None and len(iu._notes(["x" * 400])) == iu.MAX_NOTES


def test_migration_moves_old_lines_to_the_catalog_and_retires_the_field(db, factory):
    _template(db)
    ev = factory.event("creado")
    ev.set_extra({"c_inv": [{"type": "pa", "qty": 5, "ref": "Roja"}, {"type": "pa", "qty": 3, "ref": "Azul"}, {"type": "cu", "qty": 2, "ref": None}], "otro": "x"})
    sin = factory.event("creado")
    db.commit()
    stats = _run(db)
    assert stats["fields"] == 1 and stats["events"] == 1 and stats["lines"] == 2 and stats["products"] == 2
    cat = db.query(InventoryCategory).filter(InventoryCategory.name == iu.CATEGORY_NAME).one()
    prods = {p.name: p for p in db.query(InventoryProduct).all()}
    assert set(prods) == {"Pañoletas", "Cuerdas"} and all(p.category_id == cat.id for p in prods.values())
    lines = {l.product.name: l for l in db.query(EventInventoryItem).filter(EventInventoryItem.event_id == ev.id)}
    assert lines["Pañoletas"].qty_assigned == 8 and "Roja" in lines["Pañoletas"].notes and "Azul" in lines["Pañoletas"].notes
    assert lines["Cuerdas"].qty_assigned == 2 and lines["Cuerdas"].qty_out == 0 and lines["Cuerdas"].notes is None
    assert db.query(EventInventoryItem).filter(EventInventoryItem.event_id == sin.id).count() == 0
    tpl = json.loads(db.query(EventTemplate).one().fields_json)
    inv = [f for f in tpl if f["key"] == "c_inv"][0]
    assert inv["retired"] is True and inv["required"] is False and inv["config"]["inventory_types"] == TYPES          # nada se borra
    assert db.get(Event, ev.id).get_extra()["c_inv"][0]["qty"] == 5 and db.get(Event, ev.id).get_extra()["otro"] == "x"          # respaldo en extra_json


def test_migration_is_idempotent_and_never_overwrites_the_catalog(db, factory):
    _template(db)
    ev = factory.event("creado")
    ev.set_extra({"c_inv": [{"type": "pa", "qty": 5, "ref": "Roja"}]})
    db.commit()
    cat = InventoryCategory(name="Logística")
    db.add(cat)
    db.flush()
    prod = InventoryProduct(name="pañoletas", unit="und", category_id=cat.id)          # ya existe en el catálogo (otro uso de mayúsculas)
    db.add(prod)
    db.flush()
    db.add(EventInventoryItem(event_id=ev.id, product_id=prod.id, qty_assigned=99, qty_out=7))          # y el evento ya tiene su línea
    db.commit()
    first = _run(db)
    assert first["skipped"] == 1 and first["lines"] == 0 and first["products"] == 1          # solo se crea «Cuerdas»
    line = db.query(EventInventoryItem).filter(EventInventoryItem.event_id == ev.id).one()
    assert line.qty_assigned == 99 and line.qty_out == 7 and db.query(InventoryProduct).filter(InventoryProduct.name.ilike("pañoletas")).count() == 1
    second = _run(db)
    assert second["lines"] == 0 and second["products"] == 0 and db.query(InventoryProduct).count() == 2


def test_migration_without_old_fields_does_nothing(db, factory):
    factory.event("creado")
    assert _run(db) == {"fields": 0, "products": 0, "events": 0, "lines": 0, "skipped": 0}
    assert db.query(InventoryCategory).count() == 0


def test_migration_file_is_chained_and_short():
    src = (SRC / "alembic" / "versions" / "0109_inventory_unify.py").read_text(encoding="utf-8")
    assert 'revision = "0109_inventory_unify"' in src and len("0109_inventory_unify") <= 32 and 'down_revision = "0108_event_change_log"' in src and "inventory_unify.migrate" in src
