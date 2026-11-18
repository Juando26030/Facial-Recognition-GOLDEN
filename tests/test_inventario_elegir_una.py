"""19-nov-2026: grupo de inventario con «Máx. por persona = 1» = elegir UNA (ni dos ni ninguna). Pruebas sin base: la regla pura contra una base de mentira y el texto de la pantalla."""
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _Q:
    def __init__(self, rows): self.rows = rows
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def all(self): return self.rows
    def __iter__(self): return iter(self.rows)


def _db(groups, kids):
    calls = {"n": 0}
    class DB:
        def query(self, *a, **k):
            calls["n"] += 1
            return _Q(groups if calls["n"] % 2 == 1 else kids)
    return DB()


def _item(i, name, qty, parent=None, mx=None):
    return types.SimpleNamespace(id=i, name=name, initial_qty=qty, parent_id=parent, max_per_person=mx)


def test_missing_choice_message(monkeypatch):
    pytest.importorskip("fastapi")
    from app.routers import areas_inventory as ai
    g = _item(1, "Comida", 0, None, 1)
    kids = [_item(2, "Perro", 5, 1), _item(3, "Pizza", 5, 1)]
    monkeypatch.setattr(ai.subcat, "units_of", lambda *a, **k: 0)
    msg = ai.missing_required_choice(_db([g], kids), 9, "123", {}, {})
    assert "Comida" in msg and "Perro" in msg and "Pizza" in msg
    assert ai.missing_required_choice(_db([g], kids), 9, "123", {2: 1}, {}) == ""                      # eligió una
    monkeypatch.setattr(ai.subcat, "units_of", lambda *a, **k: 1)
    assert ai.missing_required_choice(_db([g], kids), 9, "123", {}, {}) == ""                          # ya recibió: no se le obliga de nuevo
    monkeypatch.setattr(ai.subcat, "units_of", lambda *a, **k: 0)
    assert ai.missing_required_choice(_db([g], kids), 9, "123", {}, {2: 5, 3: 5}) == ""                # todo agotado: no hay qué elegir


def test_screen_uses_radio_buttons_for_choose_one_and_checks_the_delivery_was_recorded():
    js = (ROOT / "static/js/inventario.js").read_text(encoding="utf-8")
    assert "type=\"radio\"" in js and "g.max_per_person === 1" in js and "fieldset[data-group]" in js
    assert "batch_id" in js and "lastBatches" in js
    srv = (ROOT / "app/routers/areas_inventory.py").read_text(encoding="utf-8")
    assert "missing_required_choice(db, event.id, user.id, wanted, delivered)" in srv and '"batch_id": batch' in srv
