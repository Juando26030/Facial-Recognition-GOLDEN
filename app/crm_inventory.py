"""CRM → inventario del evento (19-nov-2026).

Cada producto del CRM declara qué elementos de Almacén IMPLICA por unidad (`crm_product_inventory`; no descuenta existencias). Un evento nacido de una oportunidad ganada toma los productos de
la ÚLTIMA cotización vigente en el momento de ganar (`capture_at_win`) y de ahí sale lo que se le asigna en Inventario (cantidad × elementos por unidad). Después el inventario NO cambia solo:
si el CRM cambia (otro producto, otra cantidad o una cotización nueva) se crea una alerta en el inventario del evento (`detect_alert`) con lo que difiere y dos salidas: «Actualizar a lo del CRM»
(`apply_alert`) o «Descartar» (`dismiss_alert`). También se pueden agregar productos del CRM a mano (`set_manual`): el producto se expande a sus elementos, igual que si viniera del CRM.

`implied_json` de `EventCrmSync` guarda lo último que se SUMÓ al «asignado»: al sincronizar se resta lo anterior y se suma lo nuevo, así lo cargado a mano antes (eventos viejos) no se pisa.
Las partes puras (sin base) están arriba para probarlas sin Postgres. Sin commit: quien llama confirma. Sin datos personales.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:          # (importar sqlalchemy solo para los tipos: las partes puras se prueban sin base)
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------- partes puras

def whole_qty(value) -> int:
    """Cantidad entera de una línea de cotización (puede traer decimales): se redondea hacia arriba; nunca negativa."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0
    return max(int(math.ceil(n - 1e-9)), 0)


def group_products(rows: List[dict]) -> Dict[int, dict]:
    """[{crm_product_id, name, qty}] → {crm_product_id: {name, qty}} sumando repetidos; ignora filas sin producto del catálogo o sin cantidad."""
    out: Dict[int, dict] = {}
    for r in rows or []:
        pid, qty = r.get("crm_product_id"), whole_qty(r.get("qty"))
        if not pid or qty <= 0:
            continue
        cur = out.setdefault(int(pid), {"name": r.get("name") or "", "qty": 0})
        cur["qty"] += qty
        if not cur["name"]:
            cur["name"] = r.get("name") or ""
    return out


def diff_products(before: Dict[int, dict], after: Dict[int, dict]) -> List[dict]:
    """Lo que difiere entre lo que tiene el evento (`before`) y lo que dice el CRM (`after`): [{crm_product_id, name, before, after, kind}] con kind added | removed | changed."""
    out = []
    for pid in sorted(set(before) | set(after)):
        b, a = (before.get(pid) or {}).get("qty", 0), (after.get(pid) or {}).get("qty", 0)
        if b == a:
            continue
        name = (after.get(pid) or before.get(pid) or {}).get("name", "")
        out.append({"crm_product_id": pid, "name": name, "before": b, "after": a, "kind": "added" if not b else "removed" if not a else "changed"})
    return out


def snap_hash(products: Dict[int, dict]) -> str:
    canon = json.dumps({str(k): v["qty"] for k, v in sorted(products.items())}, separators=(",", ":"))
    return hashlib.sha1(canon.encode()).hexdigest()


def implied_totals(products: Dict[int, int], per_unit: Dict[int, List[tuple]]) -> Dict[int, int]:
    """{crm_product_id: cantidad} × {crm_product_id: [(id de elemento, cantidad por unidad)]} → {id de elemento: total}. 2 registros × (1 computador + 1 lector) = 2 computadores + 2 lectores."""
    out: Dict[int, int] = {}
    for pid, qty in products.items():
        for inv_id, per in per_unit.get(pid, []):
            out[inv_id] = out.get(inv_id, 0) + qty * max(int(per), 0)
    return {k: v for k, v in out.items() if v > 0}


def apply_delta(assigned: int, old_implied: int, new_implied: int, out: int = 0) -> int:
    """Nuevo «asignado» de un elemento: se resta lo que el CRM había sumado y se suma lo nuevo (lo cargado a mano se conserva), sin bajar de lo que ya salió del almacén."""
    return max((assigned or 0) - (old_implied or 0) + (new_implied or 0), out or 0, 0)


# ---------------------------------------------------------------- con base de datos

def per_unit_map(db: Session, crm_product_ids: List[int]) -> Dict[int, List[tuple]]:
    from app.models import CrmProductInventory
    out: Dict[int, List[tuple]] = {}
    if not crm_product_ids:
        return out
    for r in db.query(CrmProductInventory).filter(CrmProductInventory.crm_product_id.in_(list(crm_product_ids))).all():
        out.setdefault(r.crm_product_id, []).append((r.inventory_product_id, r.qty_per_unit))
    return out


def get_product_inventory(db: Session, crm_product_id: int) -> List[dict]:
    from app.models import CrmProductInventory, InventoryProduct
    rows = (db.query(CrmProductInventory, InventoryProduct).join(InventoryProduct, InventoryProduct.id == CrmProductInventory.inventory_product_id)
            .filter(CrmProductInventory.crm_product_id == crm_product_id).order_by(InventoryProduct.position, InventoryProduct.id).all())
    return [{"inventory_product_id": i.id, "name": i.name, "unit": i.unit, "qty_per_unit": r.qty_per_unit, "archived": i.archived_at is not None} for r, i in rows]


def set_product_inventory(db: Session, crm_product_id: int, items) -> List[dict]:
    """Reemplaza lo que implica un producto del CRM. `items` = [{inventory_product_id, qty_per_unit}]; sin repetidos, enteros de 1 a 999. Sin commit."""
    from app.crm.errors import CrmError
    from app.models import CrmProduct, CrmProductInventory, InventoryProduct
    if db.get(CrmProduct, crm_product_id) is None:
        raise CrmError("El producto no existe.", 404)
    if not isinstance(items, list) or len(items) > 60:
        raise CrmError("Envía la lista de elementos en «items» (máximo 60).")
    clean, seen = [], set()
    for it in items:
        try:
            iid, qty = int(it.get("inventory_product_id")), int(it.get("qty_per_unit"))
        except (TypeError, ValueError, AttributeError):
            raise CrmError("Cada elemento necesita su producto de Almacén y una cantidad entera.")
        if not 1 <= qty <= 999:
            raise CrmError("La cantidad por unidad va de 1 a 999.")
        if iid in seen:
            raise CrmError("Hay un elemento repetido: súmalos en una sola fila.")
        seen.add(iid)
        inv = db.get(InventoryProduct, iid)
        if inv is None:
            raise CrmError("Hay un elemento de Almacén que no existe.", 404)
        clean.append((iid, qty))
    db.query(CrmProductInventory).filter(CrmProductInventory.crm_product_id == crm_product_id).delete(synchronize_session=False)
    for iid, qty in clean:
        db.add(CrmProductInventory(crm_product_id=crm_product_id, inventory_product_id=iid, qty_per_unit=qty))
    db.flush()
    return get_product_inventory(db, crm_product_id)


def last_quote(db: Session, opportunity_id: int):
    """La cotización más reciente (no archivada) de una oportunidad: la de mayor id; cada versión nueva y cada cotización nueva tienen id mayor."""
    from app.models import CrmQuote
    return (db.query(CrmQuote).filter(CrmQuote.opportunity_id == opportunity_id, CrmQuote.archived_at.is_(None)).order_by(CrmQuote.id.desc()).first())


def quote_products(db: Session, quote_id: int) -> Dict[int, dict]:
    from app.models import CrmQuoteLine
    rows = db.query(CrmQuoteLine).filter(CrmQuoteLine.quote_id == quote_id).all()
    return group_products([{"crm_product_id": r.product_id, "name": r.name, "qty": r.qty} for r in rows])


def free_lines(db: Session, quote_id: int) -> int:
    """Líneas de la cotización sin producto del catálogo (texto libre): no implican inventario."""
    from app.models import CrmQuoteLine
    return db.query(CrmQuoteLine).filter(CrmQuoteLine.quote_id == quote_id, CrmQuoteLine.product_id.is_(None)).count()


def opportunity_of(db: Session, event_id: int):
    from app.models import CrmOpportunity
    return db.query(CrmOpportunity).filter(CrmOpportunity.event_id == event_id).first()


def event_products(db: Session, event_id: int, origin: Optional[str] = None) -> List:
    from app.models import EventCrmProduct
    q = db.query(EventCrmProduct).filter(EventCrmProduct.event_id == event_id)
    if origin:
        q = q.filter(EventCrmProduct.origin == origin)
    return q.order_by(EventCrmProduct.id).all()


def _event_totals(db: Session, event_id: int) -> Dict[int, int]:
    tot: Dict[int, int] = {}
    for r in event_products(db, event_id):
        if r.crm_product_id:
            tot[r.crm_product_id] = tot.get(r.crm_product_id, 0) + (r.qty or 0)
    return tot


def sync_inventory(db: Session, event, staff) -> Dict[int, int]:
    """Recalcula lo que IMPLICAN los productos del evento y ajusta el «asignado» de cada elemento (resta lo que se había sumado, suma lo nuevo). Devuelve {id de elemento: total implícito}. Sin commit."""
    from app.models import EventCrmSync, EventInventoryItem
    from app.timeutil import utcnow
    totals = _event_totals(db, event.id)
    new = implied_totals(totals, per_unit_map(db, list(totals)))
    sync = db.query(EventCrmSync).filter(EventCrmSync.event_id == event.id).with_for_update().first()
    if sync is None:
        sync = EventCrmSync(event_id=event.id)
        db.add(sync)
    try:
        old = {int(k): int(v) for k, v in json.loads(sync.implied_json or "{}").items()}
    except ValueError:
        old = {}
    now = utcnow()
    for iid in set(old) | set(new):
        line = db.query(EventInventoryItem).filter_by(event_id=event.id, product_id=iid).with_for_update().first()
        val = apply_delta(line.qty_assigned if line else 0, old.get(iid, 0), new.get(iid, 0), line.qty_out if line else 0)
        if line is None:
            if val == 0:
                continue
            line = EventInventoryItem(event_id=event.id, product_id=iid)
            db.add(line)
        line.qty_assigned = val
        line.updated_by_id, line.updated_at = (staff.id if staff else None), now
    sync.implied_json = json.dumps({str(k): v for k, v in new.items()})
    sync.synced_at = now
    db.flush()
    return new


def _replace_crm_rows(db: Session, event_id: int, products: Dict[int, dict], quote_id: Optional[int]) -> None:
    from app.models import EventCrmProduct, EventCrmSync
    db.query(EventCrmProduct).filter(EventCrmProduct.event_id == event_id, EventCrmProduct.origin == "crm").delete(synchronize_session=False)
    for pid, v in products.items():
        db.add(EventCrmProduct(event_id=event_id, crm_product_id=pid, name=(v["name"] or "")[:200], qty=v["qty"], origin="crm", quote_id=quote_id))
    sync = db.query(EventCrmSync).filter(EventCrmSync.event_id == event_id).first()
    if sync is None:
        sync = EventCrmSync(event_id=event_id)
        db.add(sync)
    sync.source_quote_id = quote_id
    db.flush()


def capture_at_win(db: Session, staff, opportunity, event) -> Optional[int]:
    """Al nacer el evento desde el CRM: toma los productos de la última cotización de la oportunidad y arma el inventario. Devuelve el id de la cotización usada (o None si no había). Sin commit."""
    q = last_quote(db, opportunity.id)
    if q is None:
        return None
    _replace_crm_rows(db, event.id, quote_products(db, q.id), q.id)
    sync_inventory(db, event, staff)
    return q.id


def _open_alerts(db: Session, event_id: int) -> List:
    from app.models import EventInventoryAlert
    return db.query(EventInventoryAlert).filter(EventInventoryAlert.event_id == event_id, EventInventoryAlert.status == "open").order_by(EventInventoryAlert.id).all()


def detect_alert(db: Session, event) -> Optional[object]:
    """Compara lo que tiene el evento con la última cotización de su oportunidad. Si difiere y no hay ya una alerta igual (abierta o descartada), crea una abierta; si ya coincide, cierra las abiertas como obsoletas. Sin commit."""
    from app.models import EventInventoryAlert
    from app.timeutil import utcnow
    opp = opportunity_of(db, event.id)
    if opp is None:
        return None
    q = last_quote(db, opp.id)
    if q is None:
        return None
    after = quote_products(db, q.id)
    before = group_products([{"crm_product_id": r.crm_product_id, "name": r.name, "qty": r.qty} for r in event_products(db, event.id, "crm")])
    diff = diff_products(before, after)
    open_now = _open_alerts(db, event.id)
    if not diff:
        for a in open_now:
            a.status, a.resolved_at = "obsolete", utcnow()
        return None
    h = snap_hash(after)
    same = db.query(EventInventoryAlert).filter(EventInventoryAlert.event_id == event.id, EventInventoryAlert.snap_hash == h, EventInventoryAlert.status.in_(("open", "dismissed"))).first()
    if same is not None:
        return same if same.status == "open" else None
    for a in open_now:
        a.status, a.resolved_at = "obsolete", utcnow()
    alert = EventInventoryAlert(event_id=event.id, quote_id=q.id, status="open", snapshot_json=json.dumps([{"crm_product_id": k, **v} for k, v in after.items()], ensure_ascii=False),
                                diff_json=json.dumps(diff, ensure_ascii=False), snap_hash=h)
    db.add(alert)
    db.flush()
    return alert


def apply_alert(db: Session, event, alert, staff) -> None:
    """«Actualizar a lo del CRM»: los productos de origen CRM pasan a ser los de la cotización de la alerta (los manuales no se tocan) y el inventario se recalcula. Sin commit."""
    from app.timeutil import utcnow
    snap = group_products(json.loads(alert.snapshot_json))
    _replace_crm_rows(db, event.id, snap, alert.quote_id)
    sync_inventory(db, event, staff)
    for a in _open_alerts(db, event.id):
        a.status = "applied" if a.id == alert.id else "obsolete"
        a.resolved_at, a.resolved_by_id = utcnow(), staff.id
    alert.status, alert.resolved_at, alert.resolved_by_id = "applied", utcnow(), staff.id


def dismiss_alert(db: Session, alert, staff) -> None:
    from app.timeutil import utcnow
    alert.status, alert.resolved_at, alert.resolved_by_id = "dismissed", utcnow(), staff.id


def set_manual(db: Session, event, crm_product_id: int, qty: int, staff) -> None:
    """Agrega (o cambia la cantidad de) un producto del CRM a mano en el evento; cantidad 0 lo quita. Se expande a sus elementos igual que los del CRM. Sin commit."""
    from app.crm.errors import CrmError
    from app.models import CrmProduct, EventCrmProduct
    prod = db.get(CrmProduct, crm_product_id)
    if prod is None:
        raise CrmError("El producto del CRM no existe.", 404)
    if not 0 <= qty <= 9999:
        raise CrmError("La cantidad va de 0 a 9999.")
    row = db.query(EventCrmProduct).filter(EventCrmProduct.event_id == event.id, EventCrmProduct.crm_product_id == crm_product_id, EventCrmProduct.origin == "manual").first()
    if qty == 0:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(EventCrmProduct(event_id=event.id, crm_product_id=crm_product_id, name=prod.name[:200], qty=qty, origin="manual"))
    else:
        row.qty = qty
    db.flush()
    sync_inventory(db, event, staff)


def panel(db: Session, event) -> dict:
    """Todo lo que pinta el bloque «Productos del CRM» del Inventario del evento (y detecta alertas nuevas)."""
    from app.models import CrmProduct, CrmQuote, EventInventoryAlert, InventoryProduct
    detect_alert(db, event)
    rows = event_products(db, event.id)
    ids = [r.crm_product_id for r in rows if r.crm_product_id]
    per = per_unit_map(db, ids)
    inv_names = {i.id: i for i in db.query(InventoryProduct).filter(InventoryProduct.id.in_({iid for v in per.values() for iid, _q in v} or {0})).all()}
    live = {p.id: p for p in db.query(CrmProduct).filter(CrmProduct.id.in_(ids or [0])).all()}
    products = []
    for r in rows:
        implies = [{"inventory_product_id": iid, "name": inv_names[iid].name if iid in inv_names else "?", "qty_per_unit": per_q, "total": per_q * (r.qty or 0)} for iid, per_q in per.get(r.crm_product_id, [])]
        products.append({"id": r.id, "crm_product_id": r.crm_product_id, "name": (live[r.crm_product_id].name if r.crm_product_id in live else r.name), "qty": r.qty, "origin": r.origin,
                         "implies": implies, "undeclared": not implies})
    src = None
    opp = opportunity_of(db, event.id)
    from app.models import EventCrmSync
    sync = db.query(EventCrmSync).filter(EventCrmSync.event_id == event.id).first()
    qid = sync.source_quote_id if sync else None
    if qid:
        q = db.get(CrmQuote, qid)
        if q is not None:
            src = {"quote_id": q.id, "number": q.number, "version": q.version, "title": q.title, "free_lines": free_lines(db, q.id)}
    alerts = []
    for a in db.query(EventInventoryAlert).filter(EventInventoryAlert.event_id == event.id, EventInventoryAlert.status == "open").order_by(EventInventoryAlert.id).all():
        q = db.get(CrmQuote, a.quote_id) if a.quote_id else None
        alerts.append({"id": a.id, "created_at": a.created_at.isoformat() if a.created_at else None, "quote": ({"id": q.id, "number": q.number, "version": q.version} if q else None),
                       "diff": json.loads(a.diff_json)})
    return {"has_opportunity": opp is not None, "source": src, "products": products, "alerts": alerts}


def implied_now(db: Session, event_id: int) -> Dict[int, int]:
    """Lo que los productos del evento implican hoy: {id de elemento: total}. Lo usa el plan de inventario para saber qué «asignado» viene del CRM."""
    totals = _event_totals(db, event_id)
    return implied_totals(totals, per_unit_map(db, list(totals)))


def manual_assign_allowed(db: Session, event_id: int, product_id: int, current_assigned: int) -> bool:
    """¿Se puede escribir a mano la cantidad asignada de un elemento? DECISIÓN (19-nov-2026): en un evento que nace del CRM (o que ya lleva productos del CRM) la asignación a mano de antes se eliminó:
    un elemento que viene de un producto del CRM no se escribe a mano, y solo siguen editables las líneas ANTIGUAS que ya traían cantidad. Lo nuevo se arma agregando productos del CRM.
    Un evento sin nada del CRM (creado a mano) conserva la asignación directa de siempre."""
    if implied_now(db, event_id).get(product_id, 0) > 0:
        return False
    if opportunity_of(db, event_id) is None and not event_products(db, event_id):
        return True
    return (current_assigned or 0) > 0
