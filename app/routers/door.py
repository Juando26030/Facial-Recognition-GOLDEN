"""B1 «Entrar con mi rostro»: pantalla de AUTOSERVICIO en la puerta (la persona pulsa el botón y mira a la cámara; el equipo está abierto con una cuenta del personal).

Reglas (decididas con Juan David):
  * Solo se reconoce a quien tiene una aceptación VIGENTE y verificada en este evento (la misma matriz de siempre, `faces.recognize`; nunca la vía «sin decidir» del pre-cálculo).
  * Ingreso AUTOMÁTICO solo con una coincidencia clara: distancia ≤ AUTO_MAX_DIST (0,50) y margen ≥ MATCH_MARGIN (0,06) sobre el segundo. Si no, el texto de la auditora
    «No te encontramos…» y la persona entra por cédula o QR. Sin coincidencia no se guarda nada (ni imagen ni vector): el fotograma solo vive en esta petición.
  * Supervisión sin clics: el personal ve la franja de las últimas entradas (foto de registro, nombre y hora) y puede revertir una con «revisar».
  * El límite de intentos es por PERSONA/turno y lo lleva la pantalla: tras 2 intentos seguidos sin coincidencia muestra «No te encontramos…» y se reinicia sola para la
    siguiente persona. El servidor solo pone un tope ALTO por equipo contra abuso (DOOR_ATTEMPTS_PER_MIN por cuenta del personal y evento; `rate_limit_events`, sin IP).
  * «Revisar» anula SOLO esa entrada: si la persona sigue aceptada (foto y vector intactos) puede volver a entrar por rostro, y esa nueva entrada sale marcada
    «entrada tras reversión» en la franja.
  * Si la persona ya había entrado: «Ya habías ingresado» (sin nombre) y la franja lo muestra marcado «ya había entrado» (hecho `door_face_repeat` con la entrada original).
  * Contador SOLO numérico (intentos, coincidencias, sin coincidencia) en `system_events` (sin tabla nueva): la distancia y el margen se guardan como números para calibrar el 0,50."""
import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from PIL import UnidentifiedImageError
from sqlalchemy.orm import Session

from app import crypto, faces, security
from app.auth import get_event_for_staff, require_event_in_progress, require_role
from app.database import get_db
from app.models import AccessLog, PersonChange, RateLimitEvent, StaffUser, SystemEvent, User
from app.ops import record_system_event
from app.routers.api import NOT_FOUND_FACE, _already_checked_in, _upsert_attendee
from app.storage import get_storage, photo_key
from app.timeutil import local_to_utc, to_local, utcnow

router = APIRouter()
DIGITADOR = require_role("digitador")

AUTO_MAX_DIST = float(os.getenv("DOOR_AUTO_MAX_DIST") or "0.50")      # distancia máxima para el ingreso automático (calibrar con docs/legal/GUIA_ENTRADA_ROSTRO.md)
DOOR_ATTEMPTS_PER_MIN = 30          # tope por equipo contra abuso (el de cada persona, 2 intentos, lo lleva la pantalla)
MAX_FRAME_BYTES = 3 * 1024 * 1024
METHOD = "rostro_autoservicio"
RECENT = 5
PHOTO_WINDOW = timedelta(hours=12)        # la foto de registro solo se ve en la franja para entradas recientes
NO_FACE_MSG = "No vimos tu rostro. Mira de frente a la cámara e intenta de nuevo."
OK_MSG = "¡Listo! Tu ingreso quedó registrado."
REPEAT_MSG = "Ya habías ingresado."
REVERT_DETAIL = "entrada con rostro revertida por el personal"
BUSY_MSG = "Espera un momento e intenta de nuevo."
OFF_MSG = "La entrada con rostro no está activa en este evento."


def _count(event, outcome: str, dist: float = None, margin: float = None, reason: str = "") -> None:
    """Contador numérico: «resultado dNNN mNNN» (distancia y margen en milésimas; sin cédula, sin nombre, sin imagen). Las milésimas van con letra delante para que el
    enmascarado de datos personales de `system_events` no las tome por un número largo."""
    nums = "" if dist is None else f" d{round(dist * 1000)}" + ("" if margin is None else f" m{round(margin * 1000)}")
    record_system_event("door_face", ref=str(event.id), detail=outcome + nums + (f" {reason}" if reason else ""))


def _door_event(db: Session, event_id: int, staff: StaffUser):
    event = get_event_for_staff(event_id, db, staff)
    if not (event.face_door_enabled and event.facial_enabled and not event.biometrics_locked):
        raise HTTPException(status_code=403, detail=OFF_MSG)
    return event


@router.post("/door-face")
def door_face(event_id: int = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """`file` = un fotograma. Sin prueba de vida (decisión del dueño del producto, 2026-10-16): la validación la hace la persona del equipo que supervisa la franja; regla del día del
    evento: SIEMPRE una persona frente a la pantalla de la puerta."""
    event = _door_event(db, event_id, staff)
    require_event_in_progress(event)
    key = f"{event.id}:{staff.id}"
    recent = db.query(RateLimitEvent).filter(RateLimitEvent.kind == "door_face", RateLimitEvent.key == key, RateLimitEvent.created_at > utcnow() - timedelta(minutes=1)).count()
    if recent >= DOOR_ATTEMPTS_PER_MIN:
        raise HTTPException(status_code=429, detail=BUSY_MSG)
    security.record_event(db, "door_face", key, None)
    raw = file.file.read(MAX_FRAME_BYTES + 1)
    if len(raw) > MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="La imagen es demasiado grande")
    try:
        status, ranked = faces.recognize(db, event, raw)
    except faces.Busy:
        raise HTTPException(status_code=503, detail=BUSY_MSG, headers={"Retry-After": "3"})
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="La imagen no es válida")
    finally:
        del raw                                                       # el fotograma no se guarda en ningún lado
    if status == "NO_FACE":
        _count(event, "no_face")
        return {"result": "NO_FACE", "message": NO_FACE_MSG}
    best = ranked[0] if ranked else None
    margin = (ranked[1][1] - best[1]) if len(ranked) >= 2 else None
    if status != "MATCH" or best[1] > AUTO_MAX_DIST or faces.is_doubtful(ranked):
        # motivo (solo para diagnosticar): none = ningún candidato dentro de 0,55 (o la persona no está en la matriz: sin aceptación vigente / sin vector); far = el mejor está entre
        # AUTO_MAX_DIST y 0,55; doubtful = el margen sobre el segundo es menor que MATCH_MARGIN
        reason = "none" if status != "MATCH" else ("doubtful" if faces.is_doubtful(ranked) and best[1] <= AUTO_MAX_DIST else "far")
        _count(event, "no_match", best[1] if best else None, margin, reason)
        return {"result": "NO_MATCH", "message": NOT_FOUND_FACE}
    uid = best[0]
    if db.get(User, (uid, event.tenant_id)) is None:
        _count(event, "no_match", best[1], margin)
        return {"result": "NO_MATCH", "message": NOT_FOUND_FACE}
    if _already_checked_in(db, event.id, uid):
        first = (db.query(AccessLog.id).filter(AccessLog.event_id == event.id, AccessLog.user_id == uid, AccessLog.record_type != "Actualizado")
                 .order_by(AccessLog.id).first())
        _count(event, "match_repeat", best[1], margin)
        record_system_event("door_face_repeat", ref=f"{event.id}:{first[0]}")       # solo el número interno de la entrada original: la franja la muestra «ya había entrado»
        return {"result": "ALREADY", "message": REPEAT_MSG}
    log = AccessLog(tenant_id=event.tenant_id, user_id=uid, record_type="Existente", event_id=event.id, registered_by_staff_id=staff.id, registration_method=METHOD)
    db.add(log)
    _upsert_attendee(db, event.id, uid, event.tenant_id)
    db.commit()
    reverted_before = db.query(PersonChange.id).filter(PersonChange.event_id == event.id, PersonChange.user_id == uid, PersonChange.detail == REVERT_DETAIL).first()
    if reverted_before:                                   # ya le habían revertido una entrada por rostro: la franja marca esta para que el personal la mire
        record_system_event("door_face_after_revert", ref=f"{event.id}:{log.id}")
    if event.auto_print_badge:                            # autoimpresión del evento: la pantalla de la puerta abre la escarapela (la cédula viaja solo al equipo del personal, no se muestra)
        _count(event, "match", best[1], margin)
        return {"result": "OK", "message": OK_MSG, "print_user_id": uid}
    _count(event, "match", best[1], margin)
    return {"result": "OK", "message": OK_MSG}                      # sin nombre en la pantalla pública


def _repeat_log_ids(db: Session, event, since) -> list:
    """(hora del intento repetido, id de la entrada original) de los «ya había entrado» recientes, del más nuevo al más viejo."""
    rows = (db.query(SystemEvent.at, SystemEvent.ref).filter(SystemEvent.kind == "door_face_repeat", SystemEvent.ref.like(f"{event.id}:%"), SystemEvent.at >= since)
            .order_by(SystemEvent.id.desc()).limit(RECENT).all())
    return [(at, int(ref.split(":", 1)[1])) for at, ref in rows if ref.split(":", 1)[1].isdigit()]


@router.get("/events/{event_id}/door-face/recent")
def door_recent(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """Franja de supervisión: las últimas entradas por rostro y los «ya había entrado» (para revisar sin hacer clic). La foto se pide aparte por cada línea."""
    event = get_event_for_staff(event_id, db, staff)
    rows = (db.query(AccessLog, User).join(User, (User.id == AccessLog.user_id) & (User.tenant_id == AccessLog.tenant_id))
            .filter(AccessLog.event_id == event.id, AccessLog.registration_method == METHOD).order_by(AccessLog.id.desc()).limit(RECENT).all())
    marked = {int(ref.split(":", 1)[1]) for (ref,) in db.query(SystemEvent.ref).filter(SystemEvent.kind == "door_face_after_revert", SystemEvent.ref.like(f"{event.id}:%"))
              if ref.split(":", 1)[1].isdigit()}
    out = [{"log_id": log.id, "user_id": u.id, "name": f"{u.first_name or ''} {u.last_name or ''}".strip(), "at": to_local(log.timestamp).strftime("%H:%M:%S"),
            "repeat": False, "after_revert": log.id in marked, "_sort": log.timestamp} for log, u in rows]
    for at, log_id in _repeat_log_ids(db, event, utcnow() - PHOTO_WINDOW):
        log = db.get(AccessLog, log_id)
        u = db.get(User, (log.user_id, event.tenant_id)) if log is not None and log.event_id == event.id else None
        if u is not None:
            out.append({"log_id": log.id, "user_id": u.id, "name": f"{u.first_name or ''} {u.last_name or ''}".strip(), "at": to_local(at).strftime("%H:%M:%S"), "repeat": True, "after_revert": False, "_sort": at})
    out = sorted(out, key=lambda e: e["_sort"], reverse=True)[:RECENT]
    for e in out:
        e.pop("_sort")
    return Response(content=json.dumps({"entries": out}), media_type="application/json", headers={"Cache-Control": "private, no-store"})


def _recent_log(db: Session, event, log_id: int, allow_repeat: bool = False) -> AccessLog:
    """Una entrada por rostro de este evento; con `allow_repeat`, también la entrada original (por cualquier método) de un «ya había entrado» reciente."""
    log = db.get(AccessLog, log_id)
    if log is None or log.event_id != event.id:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    if log.registration_method == METHOD:
        return log
    if allow_repeat and any(lid == log.id for _at, lid in _repeat_log_ids(db, event, utcnow() - PHOTO_WINDOW)):
        return log
    raise HTTPException(status_code=404, detail="Entrada no encontrada")


@router.get("/events/{event_id}/door-face/photo/{log_id}")
def door_photo(event_id: int, log_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """La foto de REGISTRO de quien acaba de entrar por rostro (solo entradas por rostro de las últimas 12 horas): para que el personal compare sin hacer clic."""
    event = get_event_for_staff(event_id, db, staff)
    log = _recent_log(db, event, log_id, allow_repeat=True)
    if log.registration_method == METHOD and log.timestamp < utcnow() - PHOTO_WINDOW:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    key = photo_key(event.tenant_id, log.user_id)
    content = crypto.read_bytes(key) if get_storage().exists(key) else None
    if content is None:
        raise HTTPException(status_code=404, detail="Sin foto de registro")
    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/events/{event_id}/door-face/revert/{log_id}")
def door_revert(event_id: int, log_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """«Revisar»: el personal deshace una entrada por rostro que no le cuadra. Queda en el rastro de cambios (quién y cuándo) y en el contador."""
    event = get_event_for_staff(event_id, db, staff)
    log = _recent_log(db, event, log_id)
    uid = log.user_id
    db.delete(log)
    db.add(PersonChange(tenant_id=event.tenant_id, event_id=event.id, user_id=uid, staff_user_id=staff.id, kind="registration_status",
                        old_value="Registrado", new_value="No registrado", detail=REVERT_DETAIL))
    db.commit()
    record_system_event("door_face", ref=str(event.id), detail="reverted")
    return {"reverted": True}


@router.get("/events/{event_id}/door-face/stats")
def door_stats(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(DIGITADOR)):
    """Contador de HOY (hora local): intentos, coincidencias, sin coincidencia, sin rostro y revertidas; más las distancias (solo números) para calibrar."""
    event = get_event_for_staff(event_id, db, staff)
    now_local = to_local(utcnow())
    since = local_to_utc(datetime(now_local.year, now_local.month, now_local.day))
    counts = {"match": 0, "match_repeat": 0, "no_match": 0, "no_face": 0, "no_live": 0, "reverted": 0}
    reasons: dict = {}
    attempts_list = []      # no_live: solo filas viejas de la prueba de movimiento retirada
    dists = {"match": [], "no_match": []}
    for at, detail in db.query(SystemEvent.at, SystemEvent.detail).filter(SystemEvent.kind == "door_face", SystemEvent.ref == str(event.id), SystemEvent.at >= since).order_by(SystemEvent.id):
        parts = (detail or "").split()
        if not parts or parts[0] not in counts:
            continue
        counts[parts[0]] += 1
        nums = {p[0]: int(p[1:]) / 1000 for p in parts[1:] if p[0] in "dm" and p[1:].isdigit()}
        reason = next((p for p in parts[1:] if p in ("none", "far", "doubtful")), "")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        if parts[0] != "reverted":                       # solo números y el resultado: sin cédula ni nombre. Sirve para cruzar con la hora de un intento propio
            attempts_list.append({"at": to_local(at).strftime("%H:%M:%S"), "result": parts[0], "dist": nums.get("d"), "margin": nums.get("m"), "reason": reason})
        group = "match" if parts[0].startswith("match") else parts[0]
        if group in dists and len(parts) > 1 and parts[1].startswith("d"):
            dists[group].append(int(parts[1][1:]) / 1000)
    attempts = counts["match"] + counts["match_repeat"] + counts["no_match"] + counts["no_face"] + counts["no_live"]
    return {"attempts": attempts, "matches": counts["match"] + counts["match_repeat"], "no_match": counts["no_match"] + counts["no_face"] + counts["no_live"], "no_face": counts["no_face"],
            "no_live": counts["no_live"],
            "reverted": counts["reverted"], "auto_max_dist": AUTO_MAX_DIST, "match_margin": faces.MATCH_MARGIN,
            "distances": {k: sorted(v) for k, v in dists.items()}, "reasons": reasons, "recent_attempts": attempts_list[-20:][::-1]}
