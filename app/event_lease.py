"""Arrendamiento de un evento por un servidor local (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md).

Regla: un evento tiene UN solo escritor. Mientras `Event.local_node_name` esté puesto, el evento vive en ese servidor local y la nube lo muestra en SOLO LECTURA
(nada de registrar ni editar). «Pasar a internet» libera el arrendamiento (el servidor local sube antes lo pendiente). Sin tablas nuevas: son 4 columnas del evento,
así que comprobarlo no cuesta una consulta más.

Evento COMPARTIDO (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md): si `Event.local_shared` está encendido, VARIOS servidores locales pueden tenerlo a la vez (dos entradas lejos entre sí).
El primero queda en `local_node_name` (el «principal», para todo lo que ya lo lee) y TODOS en `event_local_nodes`. Cada uno sube lo suyo y baja lo de los demás por la nube.
La nube sigue en solo lectura mientras quede al menos uno. Un evento NO compartido funciona exactamente como antes (no se consulta la tabla nueva).
"""
from fastapi import HTTPException

from app.timeutil import to_local, utcnow


def fmt_local(dt) -> str:
    return to_local(dt).strftime("%d/%m/%Y %I:%M %p")

# «Usará servidores locales» (21-nov-2026, pedido de Juan David): cómo se conectan los servidores del evento (2 o más en los tres casos). Solo `cloud` está construido;
# los otros dos (sin internet) se muestran como «Próximamente» y la nube los rechaza.
MODES = {"cloud": "Conectados con puente por la nube", "peer": "Un servidor se conecta a otro", "hub": "Un tercer servidor hace de puente"}
READY_MODES = ("cloud",)

LEASE_ROLES = ("coordinador", "comercial")      # además de admin/super_admin (jerarquía). F5-9 D5: almacén y contabilidad NO (no ven datos de asistentes); una cuenta coordinador+almacén sí, por ser coordinador (effective_roles)
NODE_NAME_MAX = 60


def is_leased(event) -> bool:
    return bool(getattr(event, "local_node_name", None))


def is_shared(event) -> bool:
    return bool(getattr(event, "local_shared", False))


def writers(event) -> list:
    """Nombres de los servidores locales que tienen el evento (el principal primero). Sin compartir: solo el principal (sin consultar la tabla nueva)."""
    if not is_leased(event):
        return []
    names = [event.local_node_name]
    if is_shared(event):
        names += [n.node_name for n in sorted(event.shared_nodes, key=lambda n: (n.joined_at, n.id or 0)) if n.node_name != event.local_node_name]
    return names


def is_writer(event, node_name) -> bool:
    """¿Este servidor local tiene el evento? (el principal, o uno del grupo si es compartido)."""
    if not node_name or not is_leased(event):
        return False
    if event.local_node_name == node_name:
        return True
    return is_shared(event) and any(n.node_name == node_name for n in event.shared_nodes)


def clean_node_name(raw) -> str:
    name = " ".join(str(raw or "").split())[:NODE_NAME_MAX]
    if not name:
        raise HTTPException(status_code=400, detail="Falta el nombre del servidor local")
    return name


def message(event) -> str:
    """Texto para mostrar a quien intenta editar: dónde está el evento y cuándo se subió lo último."""
    up = getattr(event, "local_last_upload_at", None)
    when = f"; última subida a la nube: {fmt_local(up)}" if up else "; aún no ha subido nada a la nube"
    return f"Este evento está en el servidor local «{event.local_node_name}»{when}. Solo se puede ver. Para editarlo aquí, pásalo a internet."


def assert_editable(event) -> None:
    """423 si el evento está en un servidor local (solo lectura en la nube)."""
    if is_leased(event):
        raise HTTPException(status_code=423, detail=message(event))


def assert_writable_by(event, staff) -> None:
    """423 si el evento está en un servidor local y quien escribe NO es ese servidor (su sincronización entra con el token del nodo: `staff.via_node_name`)."""
    if is_leased(event) and not is_writer(event, getattr(staff, "via_node_name", None)):
        assert_editable(event)


def serialize(event) -> dict:
    leased = is_leased(event)
    return {
        "leased": leased,
        "node_name": event.local_node_name if leased else None,
        "since": event.local_since.isoformat() if leased and event.local_since else None,
        "last_upload_at": event.local_last_upload_at.isoformat() if leased and event.local_last_upload_at else None,
        "by_name": ((event.local_by.full_name or event.local_by.username) if getattr(event, "local_by", None) else None) if leased else None,
        "message": message(event) if leased else None,
        "shared": is_shared(event),
        "mode": getattr(event, "local_mode", None) or ("cloud" if is_shared(event) else None),
        "nodes": writers(event) if leased else [],
    }


def take(event, node_name: str, staff_id: int) -> None:
    if is_leased(event):
        if is_writer(event, node_name):
            return                                           # el mismo servidor lo pide otra vez: idempotente
        if not is_shared(event):
            raise HTTPException(status_code=409, detail=f"El evento ya está en el servidor local «{event.local_node_name}». Pásalo a internet antes de llevarlo a otro "
                                                        "(o márcalo como «compartido entre varios servidores locales» en la nube).")
        _join(event, node_name)                              # evento compartido: este servidor se suma al grupo
        return
    event.local_node_name = node_name
    event.local_since = utcnow()
    event.local_by_id = staff_id
    event.local_last_upload_at = None
    if is_shared(event):
        _join(event, node_name)


def _join(event, node_name: str) -> None:
    from app.models import EventLocalNode
    if not any(n.node_name == node_name for n in event.shared_nodes):
        event.shared_nodes.append(EventLocalNode(node_name=node_name, joined_at=utcnow()))


def leave(event, node_name: str) -> bool:
    """Un servidor del grupo devuelve el evento. Si quedan otros, el evento sigue en local (si se fue el principal, el siguiente pasa a serlo) y devuelve False;
    si era el último, libera el arrendamiento y devuelve True. Sin compartir: equivale a `release`."""
    if not is_shared(event):
        release(event)
        return True
    for n in [n for n in event.shared_nodes if n.node_name == node_name]:
        event.shared_nodes.remove(n)
    rest = [n.node_name for n in sorted(event.shared_nodes, key=lambda n: (n.joined_at, n.id or 0))]
    if event.local_node_name == node_name or event.local_node_name not in rest:
        if not rest:
            release(event)
            return True
        event.local_node_name = rest[0]
    return False


def mark_uploaded(event) -> None:
    if not is_leased(event):
        raise HTTPException(status_code=409, detail="El evento no está en un servidor local")
    event.local_last_upload_at = utcnow()


def release(event) -> None:
    event.local_node_name = None
    event.local_since = None
    event.local_by_id = None
    if is_shared(event):
        event.shared_nodes.clear()
