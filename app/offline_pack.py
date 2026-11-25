"""Paquete sin red del quiosco: la parte que toca la base (docs/28_CONTINGENCIA_COMPLETA.md). Pocas consultas, sin recorrer persona por persona. Reglas en app/offline_pack_core.py."""
import hashlib
import json
from collections import defaultdict

from app import dependents as deps_mod
from app import inv_assign
from app import inv_assign_core as core
from app import offline_pack_core as pack_core
from app.models import EventAttendee, EventDependent, InventoryDelivery, User
from app.timeutil import utcnow


def build(db, event) -> dict:
    rows = [deps_mod._row_json(r) for r in db.query(EventDependent).filter(EventDependent.event_id == event.id).order_by(EventDependent.id)]
    people, own = pack_core.dependents_view(rows)
    out = {"dependents": pack_core.public_dependents(people), "assigned": None}
    if inv_assign.is_assigned(event):
        cfg = inv_assign.get_config(event)
        items = {k: {"id": i.id, "name": i.name, "initial_qty": i.initial_qty} for k, i in inv_assign._items_by_key(db, event).items()}
        stock = inv_assign._delivered_by_item(db, event.id)
        holder_done, dep_done = defaultdict(int), defaultdict(int)
        for uid, key, qty in db.query(InventoryDelivery.user_id, InventoryDelivery.assignment_key, InventoryDelivery.qty).filter(
                InventoryDelivery.event_id == event.id, InventoryDelivery.assignment_key.isnot(None)):
            if key == core.HOLDER_KEY:
                holder_done[uid] += int(qty or 0)
            else:
                dep_done[key] += int(qty or 0)
        attendee_ids = db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)
        users = [{"id": u.id, "product": inv_assign._holder_value(u, cfg["holder_product"]), "qty": inv_assign._holder_value(u, cfg["holder_qty"])}
                 for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(attendee_ids))]
        out["assigned"] = pack_core.assigned_lines(cfg, users, people, own, items, stock, holder_done, dep_done)
    body = json.dumps(out, sort_keys=True, ensure_ascii=False, default=str)
    out["v"] = hashlib.sha1(body.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    out["generated_at"] = utcnow().isoformat()
    return out
