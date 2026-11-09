"""Arrendamiento de un evento por un servidor local (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md).

Regla: un evento tiene UN solo escritor. Mientras `Event.local_node_name` esté puesto, el evento vive en ese servidor local y la nube lo muestra en SOLO LECTURA
(nada de registrar ni editar). «Pasar a internet» libera el arrendamiento (el servidor local sube antes lo pendiente). Sin tablas nuevas: son 4 columnas del evento,
así que comprobarlo no cuesta una consulta más.
"""
from fastapi import HTTPException

from app.timeutil import to_local, utcnow


def fmt_local(dt) -> str:
    return to_local(dt).strftime("%d/%m/%Y %I:%M %p")

LEASE_ROLES = ("coordinador", "comercial")      # además de admin/super_admin (jerarquía). F5-9 D5: almacén y contabilidad NO (no ven datos de asistentes); una cuenta coordinador+almacén sí, por ser coordinador (effective_roles)
NODE_NAME_MAX = 60


def is_leased(event) -> bool:
    return bool(getattr(event, "local_node_name", None))


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


def serialize(event) -> dict:
    leased = is_leased(event)
    return {
        "leased": leased,
        "node_name": event.local_node_name if leased else None,
        "since": event.local_since.isoformat() if leased and event.local_since else None,
        "last_upload_at": event.local_last_upload_at.isoformat() if leased and event.local_last_upload_at else None,
        "by_name": ((event.local_by.full_name or event.local_by.username) if getattr(event, "local_by", None) else None) if leased else None,
        "message": message(event) if leased else None,
    }


def take(event, node_name: str, staff_id: int) -> None:
    if is_leased(event):
        if event.local_node_name == node_name:
            return                                           # el mismo servidor lo pide otra vez: idempotente
        raise HTTPException(status_code=409, detail=f"El evento ya está en el servidor local «{event.local_node_name}». Pásalo a internet antes de llevarlo a otro.")
    event.local_node_name = node_name
    event.local_since = utcnow()
    event.local_by_id = staff_id
    event.local_last_upload_at = None


def mark_uploaded(event) -> None:
    if not is_leased(event):
        raise HTTPException(status_code=409, detail="El evento no está en un servidor local")
    event.local_last_upload_at = utcnow()


def release(event) -> None:
    event.local_node_name = None
    event.local_since = None
    event.local_by_id = None
