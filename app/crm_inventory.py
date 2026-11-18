"""CRM → inventario del evento (19-nov-2026).

Cada producto del CRM declara qué CATEGORÍAS de Almacén IMPLICA por unidad (`crm_product_categories`): las filas del checklist (Portátiles, Lectores, Radios…), no equipos sueltos; «Registro bidimensional» = 1 Portátiles + 1 Lectores.
Un evento nacido de una oportunidad ganada toma los productos de la ÚLTIMA cotización vigente en el momento de ganar (`capture_at_win`). El inventario NO se escribe solo: el bloque «Productos del CRM» muestra,
por categoría, lo REQUERIDO (cantidad × lo que implica cada producto) contra lo que Almacén ya ASIGNÓ al evento en esa categoría (suma de las líneas cuyo producto tiene esa fila del checklist), y Almacén elige los equipos concretos.
Si el CRM cambia después (otro producto, otra cantidad o una cotización nueva) se crea una alerta con lo que difiere y dos salidas: «Actualizar a lo del CRM» (`apply_alert`) o «Dejarlo como está» (`dismiss_alert`).
También se pueden agregar productos del CRM a mano (`set_manual`). Las partes puras (sin base) están arriba para probarlas sin Postgres. Sin commit: quien llama confirma. Sin datos personales.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, Dict, List, Optional

from app import almacen

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


# Las categorías que un producto del CRM puede implicar: filas del checklist de Almacén (decisión de Juan David, 19-nov-2026). Para ofrecer otra, se agrega aquí su clave de app/almacen.py.
CATEGORY_KEYS = ("monitores_semaforos", "modulos_touch", "tablets_ipads", "portatiles", "lectores", "impresora_hp_p1102w", "impresora_termica", "impresoras_inyeccion", "radios")


def category_options() -> List[dict]:
    return [{"key": k, "label": almacen._ROW_BY_KEY[k]["label"]} for k in CATEGORY_KEYS]


def category_label(key: str) -> str:
    row = almacen._ROW_BY_KEY.get(key)
    return row["label"] if row else key


def implied_totals(products: Dict[int, int], per_unit: Dict[int, List[tuple]]) -> Dict[str, int]:
    """{crm_product_id: cantidad} × {crm_product_id: [(clave de categoría, cantidad por unidad)]} → {clave: total}. 2 registros × (1 Portátiles + 1 Lectores) = 2 Portátiles + 2 Lectores."""
    out: Dict[str, int] = {}
    for pid, qty in products.items():
        for key, per in per_unit.get(pid, []):
            out[key] = out.get(key, 0) + qty * max(int(per), 0)
    return {k: v for k, v in out.items() if v > 0}


def requirements(needed: Dict[str, int], assigned: Dict[str, int]) -> List[dict]:
    """Lo requerido contra lo asignado por categoría: [{key, label, needed, assigned, missing}] en el orden del checklist; `missing` nunca es negativo."""
    keys = [k for k in CATEGORY_KEYS if k in needed or assigned.get(k)]
    return [{"key": k, "label": category_label(k), "needed": needed.get(k, 0), "assigned": assigned.get(k, 0), "missing": max(needed.get(k, 0) - assigned.get(k, 0), 0)} for k in keys]


# ---------------------------------------------------------------- con base de datos

def per_unit_map(db: Session, crm_product_ids: List[int]) -> Dict[int, List[tuple]]:
    from app.models import CrmProductCategory
    out: Dict[int, List[tuple]] = {}
    if not crm_product_ids:
        return out
    for r in db.query(CrmProductCategory).filter(CrmProductCategory.crm_product_id.in_(list(crm_product_ids))).order_by(CrmProductCategory.id).all():
        out.setdefault(r.crm_product_id, []).append((r.checklist_key, r.qty_per_unit))
    return out


def get_product_categories(db: Session, crm_product_id: int) -> List[dict]:
    return [{"key": k, "label": category_label(k), "qty_per_unit": q} for k, q in per_unit_map(db, [crm_product_id]).get(crm_product_id, [])]


def set_product_categories(db: Session, crm_product_id: int, items) -> List[dict]:
    """Reemplaza las categorías que implica un producto del CRM. `items` = [{key, qty_per_unit}]; claves de la lista fija, sin repetidos, enteros de 1 a 999. Sin commit."""
    from app.crm.errors import CrmError
    from app.models import CrmProduct, CrmProductCategory
    if db.get(CrmProduct, crm_product_id) is None:
        raise CrmError("El producto no existe.", 404)
    if not isinstance(items, list) or len(items) > len(CATEGORY_KEYS):
        raise CrmError("Envía la lista de categorías en «items».")
    clean, seen = [], set()
    for it in items:
        try:
            key, qty = str(it.get("key")), int(it.get("qty_per_unit"))
        except (TypeError, ValueError, AttributeError):
            raise CrmError("Cada categoría necesita su nombre y una cantidad entera.")
        if key not in CATEGORY_KEYS:
            raise CrmError("Hay una categoría que no está en la lista.")
        if not 1 <= qty <= 999:
            raise CrmError("La cantidad por unidad va de 1 a 999.")
        if key in seen:
            raise CrmError("Hay una categoría repetida: súmalas en una sola fila.")
        seen.add(key)
        clean.append((key, qty))
    db.query(CrmProductCategory).filter(CrmProductCategory.crm_product_id == crm_product_id).delete(synchronize_session=False)
    for key, qty in clean:
        db.add(CrmProductCategory(crm_product_id=crm_product_id, checklist_key=key, qty_per_unit=qty))
    db.flush()
    return get_product_categories(db, crm_product_id)


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
    """«Actualizar a lo del CRM»: los productos de origen CRM pasan a ser los de la cotización de la alerta (los manuales no se tocan); lo requerido por categoría se recalcula solo. Sin commit."""
    from app.timeutil import utcnow
    snap = group_products(json.loads(alert.snapshot_json))
    _replace_crm_rows(db, event.id, snap, alert.quote_id)
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


def implied_now(db: Session, event_id: int) -> Dict[str, int]:
    """Lo que los productos del evento requieren hoy: {clave de categoría: total}."""
    totals = _event_totals(db, event_id)
    return implied_totals(totals, per_unit_map(db, list(totals)))


def assigned_by_category(db: Session, event_id: int) -> Dict[str, int]:
    """Lo que Almacén ya asignó al evento por categoría: suma de `qty_assigned` de las líneas cuyo producto del catálogo tiene esa fila del checklist."""
    from app.models import EventInventoryItem, InventoryProduct
    out: Dict[str, int] = {}
    rows = (db.query(InventoryProduct.checklist_row, EventInventoryItem.qty_assigned).join(EventInventoryItem, EventInventoryItem.product_id == InventoryProduct.id)
            .filter(EventInventoryItem.event_id == event_id, InventoryProduct.checklist_row.isnot(None)).all())
    for key, qty in rows:
        out[key] = out.get(key, 0) + (qty or 0)
    return out


def panel(db: Session, event) -> dict:
    """Todo lo que pinta el bloque «Productos del CRM» del Inventario del evento (y detecta alertas nuevas)."""
    from app.models import CrmProduct, CrmQuote, EventCrmSync, EventInventoryAlert
    detect_alert(db, event)
    rows = event_products(db, event.id)
    ids = [r.crm_product_id for r in rows if r.crm_product_id]
    per = per_unit_map(db, ids)
    live = {p.id: p for p in db.query(CrmProduct).filter(CrmProduct.id.in_(ids or [0])).all()}
    products = []
    for r in rows:
        implies = [{"key": k, "label": category_label(k), "qty_per_unit": per_q, "total": per_q * (r.qty or 0)} for k, per_q in per.get(r.crm_product_id, [])]
        products.append({"id": r.id, "crm_product_id": r.crm_product_id, "name": (live[r.crm_product_id].name if r.crm_product_id in live else r.name), "qty": r.qty, "origin": r.origin,
                         "implies": implies, "undeclared": not implies})
    src = None
    opp = opportunity_of(db, event.id)
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
    return {"has_opportunity": opp is not None, "source": src, "products": products, "alerts": alerts,
            "requirements": requirements(implied_now(db, event.id), assigned_by_category(db, event.id))}
