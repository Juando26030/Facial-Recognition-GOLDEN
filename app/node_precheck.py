"""Consulta a la nube ANTES de una acción delicada en un servidor local de un evento COMPARTIDO (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md).

Los servidores de un evento compartido se ponen al día cada pocos segundos, pero entre una sincronización y la siguiente dos puestos podrían entregar lo mismo o dejar
entrar dos veces a una zona sin reingreso. Antes de entregar (o de registrar una entrada a una zona sin reingresos) el servidor local hace UNA consulta pequeña a la nube:
¿esta persona ya recibió esto / ya entró? Si la nube dice que sí, se frena. Si no hay internet, la acción sigue con un aviso (lo decidió Juan David: no se bloquea el
evento por falta de red) y una entrega doble se ve después en «Entregas de más». Sin consultas periódicas: solo una por acción, con un tiempo máximo corto."""
import logging
from typing import Optional

log = logging.getLogger("golden.node_precheck")
TIMEOUT = 3.0
OFFLINE_WARNING = "No se pudo consultar a la nube antes de esta acción (sin internet): se hizo igual. Si otro puesto ya lo había hecho, se verá al sincronizar."


def enabled(event) -> bool:
    from app import node_sync
    return bool(node_sync.is_local_server() and getattr(event, "local_shared", False) and getattr(event, "cloud_event_id", None) and node_sync.configured())


def ask(event, cedula: str, keys=None, items=None, areas=None) -> Optional[dict]:
    """{"keys": {clave: unidades}, "items": {nombre en minúsculas: unidades}, "areas": {nombre en minúsculas: True}} de la nube, o None si no se pudo preguntar."""
    if not enabled(event):
        return {"keys": {}, "items": {}, "areas": {}, "skipped": True}
    from app import node_sync
    try:
        out = node_sync._call("POST", f"/api/node/events/{int(event.cloud_event_id)}/precheck",
                              {"cedula": str(cedula), "keys": list(keys or [])[:200], "items": list(items or [])[:200], "areas": list(areas or [])[:50]}, timeout=TIMEOUT)
    except Exception:  # noqa: BLE001 — sin internet o la nube no responde: la acción sigue con aviso
        log.info("consulta previa: sin respuesta de la nube (evento %s)", event.id)
        return None
    return {"keys": dict(out.get("keys") or {}), "items": dict(out.get("items") or {}), "areas": dict(out.get("areas") or {})}


def cloud_answer(db, event, body: dict) -> dict:
    """Lo que responde la NUBE: lo que ya tiene registrado de esa persona (lo suyo y lo que subieron los demás servidores). Solo conteos."""
    from sqlalchemy import func
    from app import inv_assign_core as core
    from app.models import AreaMovement, EventArea, InventoryDelivery, InventoryItem
    cedula = str(body.get("cedula") or "")[:64]
    keys = [str(k)[:40] for k in (body.get("keys") or [])][:200]
    out = {"keys": {}, "items": {}, "areas": {}}
    if not cedula:
        return out
    if keys:
        holder = [k for k in keys if k == core.HOLDER_KEY]
        deps = [k for k in keys if k != core.HOLDER_KEY]
        if holder:
            q = db.query(func.coalesce(func.sum(InventoryDelivery.qty), 0)).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.user_id == cedula,
                                                                                 InventoryDelivery.assignment_key == core.HOLDER_KEY).scalar()
            out["keys"][core.HOLDER_KEY] = int(q or 0)
        if deps:
            for k, q in db.query(InventoryDelivery.assignment_key, func.sum(InventoryDelivery.qty)).filter(InventoryDelivery.event_id == event.id,
                                                                                                         InventoryDelivery.assignment_key.in_(deps)).group_by(InventoryDelivery.assignment_key):
                out["keys"][k] = int(q or 0)
    names = [str(n).strip().lower()[:200] for n in (body.get("items") or [])][:200]
    if names:
        for name, q in db.query(func.lower(InventoryItem.name), func.sum(InventoryDelivery.qty)).join(InventoryItem, InventoryItem.id == InventoryDelivery.item_id).filter(
                InventoryDelivery.event_id == event.id, InventoryDelivery.user_id == cedula, func.lower(InventoryItem.name).in_(names)).group_by(func.lower(InventoryItem.name)):
            out["items"][name] = int(q or 0)
    areas = [str(n).strip().lower()[:200] for n in (body.get("areas") or [])][:50]
    if areas:
        for (name,) in db.query(func.lower(EventArea.name)).join(AreaMovement, AreaMovement.area_id == EventArea.id).filter(
                AreaMovement.event_id == event.id, AreaMovement.user_id == cedula, AreaMovement.direction == "in", func.lower(EventArea.name).in_(areas)).distinct():
            out["areas"][name] = True
    return out
