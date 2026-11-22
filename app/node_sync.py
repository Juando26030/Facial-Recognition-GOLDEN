"""Subida del servidor LOCAL hacia la nube (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md). Solo corre con LOCAL_SERVER=1 (en la nube no hace nada y no toca la base).

Cada ~NODE_UPLOAD_MINUTES (30) y cuando alguien lo pide, el servidor local sube lo que tenga de cada evento que bajó de la nube (`Event.cloud_event_id`):
  1. personas dadas de alta aquí (origen manual / autoregistro)  -> POST /api/node/events/{id}/outbox      (`create_person`, idempotente por op_id)
  2. ingresos de personas que ya estaban (AccessLog «Existente») -> POST /api/node/events/{id}/access-logs (idempotente por client_id)
  3. impresiones y cambios de personas (deshacer registro, fecha de nacimiento) -> POST /api/node/events/{id}/records (la nube también APLICA el cambio desde 0160)
  4. (0160) ediciones de datos, movimientos de áreas, entregas de inventario, turnos (y su estado) y llamados -> POST /api/node/events/{id}/extra (app/node_extra.py)
Las marcas de agua (`sync_persons_at`, `sync_log_id`) solo avanzan con lo que la nube CONFIRMÓ: un corte a mitad de camino repite el lote y la nube responde «replayed».
Cuando todo lo pendiente quedó confirmado se avisa `/uploaded` (la nube muestra «última subida a las 3:30 p. m.»). «Pasar a internet» = subir lo pendiente y, solo si quedó en cero, `/release`.
Evento COMPARTIDO (0160, docs/23_EVENTO_COMPARTIDO_NUBE.md): si varios servidores tienen el mismo evento, mientras esté «En proceso» cada NODE_SHARED_SECONDS (15) este servidor sube lo
suyo y BAJA lo de los demás (`pull_event`, app/peer_changes.py). Lo bajado queda marcado `from_peer` y nunca se vuelve a subir. Los identificadores que sube llevan el prefijo propio del
servidor (peer_changes.node_tag) para que dos servidores no choquen.
Configuración (variables de entorno): PRODUCTION_URL (https), NODE_TOKEN (el token que mostró la nube al crear el servidor), NODE_UPLOAD_MINUTES, NODE_SHARED_SECONDS.
Nada de datos personales en los logs; los errores guardados (`sync_error`) son texto corto sin cédulas ni nombres.
"""
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import timedelta, timezone
from typing import Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app import local_env, peer_changes, versioning
from app.models import (AccessLog, AreaMovement, AuditConsentLog, Event, EventAttendee, ExhibitorLead, InventoryDelivery, PersonChange, PersonChangeLog, PrintLog, QueueCall, QueueTurn,
                        RouletteDraw, User, WebAcceptance)
from app.timeutil import utcnow

log = logging.getLogger("golden.node_sync")
HTTP_TIMEOUT = 20.0
MIN_GAP = timedelta(seconds=60)                      # dos procesos del mismo servidor no suben el mismo evento a la vez
PERSON_ORIGINS = ("manual", "autoregistro")
LOG_TYPE = "Existente"
BATCH_LOGS, BATCH_OPS, BATCH_REC = 400, 100, 400                     # por debajo de los topes de la nube (SYNC_MAX_RECORDS 500 / OUTBOX_MAX_OPS)
_run_lock = threading.Lock()


class SyncError(Exception):
    """Fallo esperable (sin red, versión incompatible, la nube rechazó): se guarda su texto corto y se reintenta en el siguiente ciclo."""


# ------------------------------------------------------------------------------------------------ configuración
def is_local_server() -> bool:
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def node_token() -> str:
    local_env.refresh()
    return (os.getenv("NODE_TOKEN") or "").strip()


def interval_minutes() -> int:
    try:
        return max(1, int(os.getenv("NODE_UPLOAD_MINUTES", "30")))
    except ValueError:
        return 30


def shared_seconds() -> int:
    try:
        return max(5, int(os.getenv("NODE_SHARED_SECONDS", "15")))
    except ValueError:
        return 15


def configured() -> bool:
    return is_local_server() and bool(versioning.production_url()) and bool(node_token())


# ------------------------------------------------------------------------------------------------ HTTP hacia la nube
def _headers() -> dict:
    v = versioning.local_version()
    return {"Content-Type": "application/json", "Accept": "application/json", "X-Node-Token": node_token(), "X-Node-Version": f"{v['commit']}|{v['schema']}"[:80], "X-Node-Schema": v["schema"]}


def _call(method: str, path: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
    url = versioning.production_url()
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        raise SyncError("PRODUCTION_URL debe ser https")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method, headers=_headers())
    from app.cloud_client import open_no_redirect
    try:
        with open_no_redirect(req, timeout=timeout or HTTP_TIMEOUT) as resp:      # F5-9 A-10: sin redirecciones (el token no viaja a otra dirección)
            out = json.loads(resp.read(2_000_000).decode("utf-8") or "{}")
        from app import server_lock
        server_lock.note_cloud_ok()                              # la nube reconoció a este servidor: reinicia el plazo de gracia (app/server_lock.py)
        return out
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read(5000).decode("utf-8")).get("detail")
        except (ValueError, OSError):
            detail = None
        from app import server_lock
        server_lock.note_cloud_error(e.code, detail)
        raise SyncError(str(detail)[:200] if isinstance(detail, str) else f"La nube respondió {e.code}")
    except (urllib.error.URLError, OSError, ValueError):
        raise SyncError("Sin conexión con la nube")


def _call_bytes(path: str, data: bytes, content_type: str) -> dict:
    """Como `_call` pero con un cuerpo crudo (la copia completa y sus archivos, app/local_backup.py)."""
    url = versioning.production_url()
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        raise SyncError("PRODUCTION_URL debe ser https")
    headers = {**_headers(), "Content-Type": content_type}
    req = urllib.request.Request(url + path, data=data, method="POST", headers=headers)
    from app.cloud_client import open_no_redirect
    try:
        with open_no_redirect(req, timeout=120) as resp:
            return json.loads(resp.read(200_000).decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise SyncError(f"La nube no recibió la copia completa ({e.code})")
    except (urllib.error.URLError, OSError, ValueError):
        raise SyncError("Sin conexión con la nube")


def _setting(db: Session, key: str):
    from app.models import AppSetting
    row = db.get(AppSetting, key)
    return row.value if row else None


def _set_setting(db: Session, key: str, value: str) -> None:
    from app.models import AppSetting
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_at=utcnow()))
    else:
        row.value, row.updated_at = value, utcnow()


def push_backup(db: Session, event: Event) -> dict:
    """0160: sube la COPIA COMPLETA del evento (si cambió desde la última) y los archivos nuevos que nombra. Seguro contra la pérdida del servidor: lo que la fusión fila por fila no
    cubra queda igual en la nube (app/local_backup.py). Lanza SyncError si no hay red."""
    from urllib.parse import quote
    from app import local_backup
    from app.storage import get_storage
    gz, digest = local_backup.build(db, event)
    hash_key, files_key = f"local_backup_hash:{event.id}", f"local_backup_files:{event.id}"
    sent_copy = False
    if _setting(db, hash_key) != digest:
        if len(gz) > local_backup.MAX_BACKUP_BYTES:
            raise SyncError("La copia completa del evento es demasiado grande para subirla de una vez")
        _call_bytes(f"/api/node/events/{event.cloud_event_id}/backup", gz, "application/gzip")
        _set_setting(db, hash_key, digest)
        db.commit()
        sent_copy = True
    try:
        done = set(json.loads(_setting(db, files_key) or "[]"))
    except ValueError:
        done = set()
    import gzip as _gz
    keys = local_backup.file_keys(json.loads(_gz.decompress(gz).decode("utf-8")))
    st, sent_files = get_storage(), 0
    for k in local_backup.iter_new(keys, done):
        try:
            if not st.exists(k):
                done.add(k)
                continue
            data = st.get(k)
        except Exception:                                   # noqa: BLE001 — un archivo ilegible no frena la copia
            continue
        if len(data) <= local_backup.MAX_FILE_BYTES:
            _call_bytes(f"/api/node/events/{event.cloud_event_id}/backup-file?key={quote(k)}", data, "application/octet-stream")
            sent_files += 1
        done.add(k)
        _set_setting(db, files_key, json.dumps(sorted(done)))
        db.commit()
    return {"copy": sent_copy, "files": sent_files}


def cloud_ping() -> dict:
    """Pregunta a la nube si nos acepta (token válido y versión compatible)."""
    out = _call("GET", "/api/node/ping")
    if not out.get("compatible"):
        raise SyncError(out.get("message") or "Versión incompatible con la nube")
    return out


# ------------------------------------------------------------------------------------------------ lo pendiente
def _persons_query(db: Session, event: Event):
    q = db.query(EventAttendee).filter(EventAttendee.event_id == event.id, EventAttendee.origin.in_(PERSON_ORIGINS), EventAttendee.from_peer.isnot(True))          # lo bajado de otro servidor no se devuelve
    if event.sync_persons_at is not None:
        q = q.filter(EventAttendee.created_at > event.sync_persons_at)
    return q


def _logs_query(db: Session, event: Event):
    q = db.query(AccessLog).filter(AccessLog.event_id == event.id, AccessLog.from_peer.isnot(True))
    if event.sync_log_id is not None:
        q = q.filter(AccessLog.id > event.sync_log_id)
    return q


def _prints_query(db: Session, event: Event):
    q = db.query(PrintLog).filter(PrintLog.event_id == event.id, PrintLog.from_peer.isnot(True))
    if event.sync_print_id is not None:
        return q.filter(PrintLog.id > event.sync_print_id)
    return q.filter(PrintLog.printed_at > event.sync_package_at) if event.sync_package_at is not None else q.filter(False)          # sin marca: solo lo hecho DESPUÉS de bajar el evento


def _changes_query(db: Session, event: Event):
    q = db.query(PersonChange).filter(PersonChange.event_id == event.id, PersonChange.from_peer.isnot(True))
    if event.sync_change_id is not None:
        return q.filter(PersonChange.id > event.sync_change_id)
    return q.filter(PersonChange.at > event.sync_package_at) if event.sync_package_at is not None else q.filter(False)


# 0160: lo que antes se quedaba aquí y ahora también sube (app/node_extra.py). (modelo, columna de id, marca de agua del evento, columna de fecha para «después de bajar el paquete»)
EXTRA = (
    ("edits", PersonChangeLog, "sync_edit_id", "changed_at"),
    ("areas", AreaMovement, "sync_area_id", "timestamp"),
    ("deliveries", InventoryDelivery, "sync_delivery_id", "delivered_at"),
    ("turns", QueueTurn, "sync_turn_id", "created_at"),
    ("calls", QueueCall, "sync_call_id", "called_at"),
    ("roulette", RouletteDraw, "sync_roulette_id", "created_at"),
    ("leads", ExhibitorLead, "sync_lead_id", "scanned_at"),
)


def _accept_query(db: Session, event: Event):
    """Aceptaciones/firmas creadas o verificadas aquí después de la última subida (la hora la pone este servidor)."""
    since = event.sync_accept_at or event.sync_package_at
    if since is None:
        return db.query(WebAcceptance).filter(False)
    return db.query(WebAcceptance).filter(WebAcceptance.event_id == event.id, WebAcceptance.from_peer.isnot(True),
                                          or_(WebAcceptance.created_at > since, WebAcceptance.verified_at > since))


CONSENT_SENT = "sync_consent_ids:{}"          # AppSetting: ids de autorizaciones ya confirmadas por la nube (la tabla no admite marcar filas: es solo INSERT)


def _consent_sent(db: Session, event: Event) -> set:
    from app.models import AppSetting
    row = db.get(AppSetting, CONSENT_SENT.format(event.id))
    try:
        return set(json.loads(row.value)) if row and row.value else set()
    except ValueError:
        return set()


def _consent_pending(db: Session, event: Event) -> list:
    """Autorizaciones hechas aquí que la nube aún no confirmó. Por id (no por hora: una autorización de un quiosco sin red llega tarde con su hora original)."""
    if event.sync_package_at is None:
        return []
    since = event.sync_package_at.replace(tzinfo=timezone.utc)
    sent = _consent_sent(db, event)
    rows = db.query(AuditConsentLog).filter(AuditConsentLog.event_id == event.id, AuditConsentLog.from_peer.isnot(True), AuditConsentLog.consent_timestamp_utc > since)
    return [r for r in rows.order_by(AuditConsentLog.consent_timestamp_utc) if r.id not in sent]


def _mark_consents_sent(db: Session, event: Event, ids: list) -> None:
    from app.models import AppSetting
    key = CONSENT_SENT.format(event.id)
    sent = _consent_sent(db, event) | set(ids)
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=json.dumps(sorted(sent)), updated_at=utcnow()))
    else:
        row.value, row.updated_at = json.dumps(sorted(sent)), utcnow()


def _extra_query(db: Session, event: Event, model, mark: str, when_col: str):
    q = db.query(model).filter(model.event_id == event.id, model.from_peer.isnot(True))
    last = getattr(event, mark)
    if last is not None:
        return q.filter(model.id > last)
    return q.filter(getattr(model, when_col) > event.sync_package_at) if event.sync_package_at is not None else q.filter(False)


def _turn_status_query(db: Session, event: Event):
    """Turnos YA enviados cuyo estado cambió después de la última subida (llamado, atendido, saltado)."""
    if event.sync_turn_id is None or event.sync_turn_at is None:
        return None
    since = event.sync_turn_at
    return db.query(QueueTurn).filter(QueueTurn.event_id == event.id, QueueTurn.id <= event.sync_turn_id, QueueTurn.from_peer.isnot(True),
                                      or_(QueueTurn.called_at > since, QueueTurn.done_at > since))


def pending_counts(db: Session, event: Event) -> dict:
    persons = _persons_query(db, event).count()
    logs = _logs_query(db, event).filter(AccessLog.record_type == LOG_TYPE).count()
    prints = _prints_query(db, event).count()
    changes = _changes_query(db, event).count()
    extra = sum(_extra_query(db, event, model, mark, col).count() for _, model, mark, col in EXTRA) + _accept_query(db, event).count() + len(_consent_pending(db, event))
    return {"persons": persons, "logs": logs, "prints": prints, "changes": changes, "extra": extra, "total": persons + logs + prints + changes + extra}


# Lo que se hace en el servidor local y TODAVÍA NO SUBE a la nube (la subida solo lleva personas nuevas e ingresos). Mientras exista algo así,
# «Pasar a internet» NO libera el evento: se perdería sin aviso (revisión 9-nov-2026, docs/FASE_6_SERVIDOR_LOCAL.md). Nombres fijos (no vienen del usuario).
LOCAL_ONLY = (          # 0160: áreas, entregas de inventario, turnos, llamados, ruleta, expositores, aceptaciones y autorizaciones ya SUBEN (app/node_extra.py) y salieron de esta lista
    ("event_inventory_items", "updated_at", "cambios del inventario del evento"),          # almacén: en el servidor local es de solo consulta (no hay catálogo); si algo cambiara, igual queda en la copia completa
)


def allow_local_only_loss() -> bool:
    """Válvula de emergencia (variable de entorno del servidor local): liberar aunque se pierdan datos que no suben. Por defecto apagada."""
    return os.getenv("NODE_RELEASE_ALLOW_LOCAL_ONLY", "").strip().lower() in ("1", "true", "si", "sí", "yes")


def local_only_changes(db: Session, event: Event) -> dict:
    """{etiqueta: cantidad} de lo hecho aquí DESPUÉS de bajar el evento que la subida no lleva. Vacío = se puede liberar sin perder nada."""
    since = event.sync_package_at
    if since is None:
        return {}
    out = {}
    for table, column, label in LOCAL_ONLY:
        try:
            n = db.execute(text(f"SELECT count(*) FROM {table} WHERE event_id = :e AND {column} > :t"), {"e": event.id, "t": since}).scalar() or 0
        except Exception:                                   # tabla ausente en una base vieja: no bloquea por eso
            db.rollback()
            continue
        if n:
            out[label] = int(n)
    return out


def synced_events(db: Session) -> list:
    return db.query(Event).filter(Event.cloud_event_id.isnot(None)).order_by(Event.id).all()


# ------------------------------------------------------------------------------------------------ subir un evento
def _person_op(db: Session, event: Event, att: EventAttendee) -> Optional[dict]:
    u = db.query(User).filter(User.id == att.user_id, User.tenant_id == att.tenant_id).first()
    if u is None:
        return None
    fields = {"id": u.id, "first_name": u.first_name, "last_name": u.last_name, "role": u.role, "entity": u.entity, "phone": u.phone, "email": u.email, "opt_1": u.opt_1,
              "extra_fields": u.get_extras(), "categories": att.get_categories(), "field_labels": event.get_optional_labels()}
    op_id = f"{peer_changes.node_tag()}-{event.id}-p{att.id}" if event.local_shared else f"n{event.id}-p{att.id}"          # compartido: con el prefijo de este servidor (no choca con otro)
    return {"op_id": op_id[:64], "type": "create_person", "timestamp": (att.created_at or utcnow()).isoformat(), "fields": fields}


def _push_persons(db: Session, event: Event) -> None:
    base = f"/api/node/events/{event.cloud_event_id}/outbox"
    while True:
        batch = _persons_query(db, event).order_by(EventAttendee.created_at, EventAttendee.id).limit(BATCH_OPS).all()
        if not batch:
            return
        pairs = [(att, _person_op(db, event, att)) for att in batch]
        ops = [op for _, op in pairs if op]
        results = {}
        if ops:
            out = _call("POST", base, {"ops": ops})
            results = {r.get("op_id"): r for r in out.get("results", [])}
        for att, op in pairs:
            res = results.get(op["op_id"]) if op else {"result": "ok"}
            if not res or res.get("result") not in ("ok", "replayed", "existente", "duplicado"):
                raise SyncError("La nube no aceptó un alta hecha en este servidor: " + str((res or {}).get("detail") or "sin respuesta")[:120])
        event.sync_persons_at = batch[-1].created_at or utcnow()
        db.commit()


def _log_record(event: Event, row: AccessLog) -> dict:
    return {"client_id": (row.client_id or f"n{event.id}-l{row.id}")[:64], "cedula": row.user_id, "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "method": "qr" if row.registration_method == "qr" else "cedula"}


def _push_logs(db: Session, event: Event) -> None:
    path = f"/api/node/events/{event.cloud_event_id}/access-logs"
    while True:
        batch = _logs_query(db, event).order_by(AccessLog.id).limit(BATCH_LOGS).all()
        if not batch:
            return
        send = [r for r in batch if r.record_type == LOG_TYPE]
        if event.local_shared:                          # compartido: el identificador se fija AQUÍ con el prefijo de este servidor, para reconocerlo cuando vuelva de la nube
            tag = peer_changes.node_tag()
            for r in send:
                if not r.client_id:
                    r.client_id = f"{tag}-{event.id}-l{r.id}"[:64]
            db.flush()
        if send:
            out = _call("POST", path, {"records": [_log_record(event, r) for r in send]})
            bad = [r for r in out.get("results", []) if r.get("result") == "invalid"]
            if bad or len(out.get("results", [])) != len(send):
                raise SyncError("La nube rechazó ingresos del lote: se reintenta")
        event.sync_log_id = batch[-1].id
        db.commit()


def _push_records(db: Session, event: Event) -> None:
    """Impresiones y ediciones de personas hechas aquí (historial). Avanzan sus marcas de agua solo con lo que la nube confirmó."""
    path = f"/api/node/events/{event.cloud_event_id}/records"
    while True:
        prints = _prints_query(db, event).order_by(PrintLog.id).limit(BATCH_REC).all()
        changes = _changes_query(db, event).order_by(PersonChange.id).limit(BATCH_REC).all()
        if not prints and not changes:
            return
        body = {"print_logs": [{"cedula": p.user_id, "printed_at": p.printed_at.isoformat() if p.printed_at else None, "kind": p.kind} for p in prints],
                "person_changes": [{"cedula": c.user_id, "at": c.at.isoformat() if c.at else None, "kind": c.kind, "old_value": c.old_value, "new_value": c.new_value, "detail": c.detail} for c in changes]}
        out = _call("POST", path, body)
        if not out.get("ok"):
            raise SyncError("La nube no confirmó las impresiones o ediciones del lote: se reintenta")
        if prints:
            event.sync_print_id = prints[-1].id
        if changes:
            event.sync_change_id = changes[-1].id
        db.commit()


def _push_extra(db: Session, event: Event) -> None:
    """0160: ediciones de datos, áreas, entregas de inventario, turnos (y su estado) y llamados. Cada marca de agua avanza solo con lo que la nube confirmó."""
    from app import node_extra
    path = f"/api/node/events/{event.cloud_event_id}/extra"
    areas, items, exhibitors = node_extra.area_names(db, event.id), node_extra.item_names(db, event.id), node_extra.exhibitor_map(db, event.id)
    ser = {"edits": node_extra.edit_row, "areas": lambda r: node_extra.area_row(r, areas), "deliveries": lambda r: node_extra.delivery_row(r, items),
           "turns": node_extra.turn_row, "calls": node_extra.call_row, "roulette": node_extra.roulette_row, "leads": lambda r: node_extra.lead_row(r, exhibitors)}
    while True:
        rows = {key: _extra_query(db, event, model, mark, col).order_by(model.id).limit(BATCH_REC).all() for key, model, mark, col in EXTRA}
        status_q = _turn_status_query(db, event)
        status_rows = status_q.limit(BATCH_REC).all() if status_q is not None else []
        accepts = _accept_query(db, event).limit(BATCH_REC).all()
        consents = _consent_pending(db, event)[:BATCH_REC]
        if not any(rows.values()) and not status_rows and not accepts and not consents:
            return
        body = {key: [x for x in (ser[key](r) for r in batch) if x] for key, batch in rows.items()}
        body["turn_status"] = [node_extra.turn_row(t) for t in status_rows]
        body["acceptances"] = [node_extra.acceptance_row(a) for a in accepts]
        body["consents"] = [node_extra.consent_row(c) for c in consents]
        started = utcnow()
        out = _call("POST", path, body)
        if not out.get("ok"):
            raise SyncError("La nube no confirmó lo subido del lote (áreas, inventario, turnos, ediciones, ruleta, expositores, aceptaciones o autorizaciones): se reintenta")
        for key, model, mark, _col in EXTRA:
            if rows[key]:
                setattr(event, mark, rows[key][-1].id)
        if rows["turns"] or status_rows or event.sync_turn_at is None:
            event.sync_turn_at = started
        if accepts or event.sync_accept_at is None:
            event.sync_accept_at = started
        if consents:
            _mark_consents_sent(db, event, [c.id for c in consents])
        db.commit()
        if not any(rows.values()) and len(consents) < BATCH_REC:
            return                                             # solo estados de turnos / aceptaciones: una pasada basta


def pull_event(db: Session, event: Event, max_pages: int = 20) -> dict:
    """Evento compartido: baja de la nube lo que hicieron los OTROS servidores desde el cursor y lo aplica aquí (sin duplicar). Lanza SyncError si no hay red."""
    total = {"persons": 0, "access_logs": 0, "print_logs": 0, "person_changes": 0}
    cur = peer_changes.clean_cursor(event.peer_cursor)
    for _ in range(max_pages):
        q = "&".join(f"{k}={cur[k]}" for k in peer_changes.KEYS)
        data = _call("GET", f"/api/node/events/{event.cloud_event_id}/changes?{q}")
        added = peer_changes.apply_changes(db, event, data)
        for k, v in added.items():
            total[k] = total.get(k, 0) + v                    # `added` también trae las secciones de node_extra (edits, areas…): sin .get, la primera edición bajada daba KeyError
        cur = peer_changes.clean_cursor(data.get("cursor") or cur)
        peer_changes.save_cursor(event, cur)
        db.commit()
        if not data.get("more"):
            break
    if any(total.values()):
        log.info("evento compartido %s: bajado de otros servidores %s", event.id, total)
    return total


def sync_shared(db: Session, event: Event) -> dict:
    """Ciclo corto de un evento compartido: subir lo propio y bajar lo de los demás. Sin ping (cada llamada ya lleva la versión y la nube la revisa). No lanza."""
    try:
        _push_persons(db, event)
        _push_logs(db, event)
        _push_records(db, event)
        _push_extra(db, event)
        pulled = pull_event(db, event)
        if event.sync_error:
            event.sync_error = None
            db.commit()
        return {"ok": True, "pulled": pulled}
    except SyncError as e:
        db.rollback()
        ev = db.get(Event, event.id)
        ev.sync_error = str(e)[:300]
        db.commit()
        return {"ok": False, "error": str(e)}


def _refresh_shared_flags(db: Session, ping: dict) -> None:
    """La nube dice (en el ping) qué eventos de este servidor son compartidos: así se entera un servidor que ya tenía el evento cuando lo marcan como compartido después."""
    shared = ping.get("shared_events")
    if not isinstance(shared, list):
        return
    ids = {int(x) for x in shared if isinstance(x, int)}
    changed = False
    for ev in synced_events(db):
        want = ev.cloud_event_id in ids
        if bool(ev.local_shared) != want:
            ev.local_shared = want
            changed = True
    if changed:
        db.commit()


def upload_event(db: Session, event: Event, *, force: bool = False) -> dict:
    """Sube lo pendiente de UN evento. Devuelve {"ok", "pending", "error"}. No lanza: guarda el motivo en `sync_error`."""
    if event.cloud_event_id is None:
        return {"ok": False, "pending": 0, "error": "Este evento no es una copia de la nube"}
    now = utcnow()
    if not force and event.sync_attempt_at is not None and now - event.sync_attempt_at < MIN_GAP:
        return {"ok": True, "pending": pending_counts(db, event)["total"], "error": None, "skipped": True}
    event.sync_attempt_at = now
    db.commit()
    try:
        cloud_ping()
        _push_persons(db, event)             # primero las personas nuevas: los ingresos de esa misma gente ya las encuentran
        _push_logs(db, event)
        _push_records(db, event)
        _push_extra(db, event)
        if event.local_shared:
            pull_event(db, event)                # compartido: de paso baja lo de los demás servidores
        push_backup(db, event)                   # 0160: y la copia completa (si cambió): nada queda solo en este servidor
        counts = pending_counts(db, event)
        if counts["total"] == 0:
            _call("POST", f"/api/node/events/{event.cloud_event_id}/uploaded")
            event.local_last_upload_at = utcnow()
        event.sync_error = None
        db.commit()
        return {"ok": True, "pending": counts["total"], "error": None}
    except SyncError as e:
        db.rollback()
        ev = db.get(Event, event.id)
        ev.sync_error = str(e)[:300]
        db.commit()
        log.warning("subida del evento local %s falló: %s", event.id, e)
        return {"ok": False, "pending": pending_counts(db, ev)["total"], "error": str(e)}


def _refresh_accounts(db: Session) -> None:
    from app import account_sync
    try:
        account_sync.run_once(db)
    except Exception:                                        # noqa: BLE001 — sin red o respuesta rara: nunca frena la subida
        db.rollback()
        log.warning("no se pudieron actualizar las cuentas desde la nube")


def refresh_checklist(db: Session, ev: Event) -> bool:
    """Pone al día la foto del checklist de inventario de UN evento descargado (solo lectura; sin datos de personas). Sin internet o con un fallo, se conserva la anterior. True si se actualizó."""
    from app import cloud_client, event_checklist
    try:
        event_checklist.save_snapshot(db, ev.id, cloud_client.inventory_checklist(ev.cloud_event_id))
        db.commit()
        return True
    except Exception:                                        # noqa: BLE001  (sin internet: normal)
        db.rollback()
        return False


def _refresh_checklists(db: Session) -> None:
    """Mientras hay internet, deja puesta al día la foto del checklist de cada evento descargado."""
    for ev in synced_events(db):
        refresh_checklist(db, ev)


def upload_all(db: Session, *, force: bool = False) -> dict:
    """Un ciclo: todos los eventos bajados de la nube. Un fallo en uno no detiene a los demás."""
    if not configured():
        return {"configured": False, "events": 0}
    if not _run_lock.acquire(blocking=False):
        return {"configured": True, "busy": True, "events": 0}
    try:
        try:
            _refresh_shared_flags(db, cloud_ping())
        except SyncError:
            pass                                             # sin red: cada evento lo reintenta abajo y guarda su motivo
        _refresh_accounts(db)                                # al conectarse y en cada ciclo de ~30 min: cuentas y contraseñas de la nube (la nube manda)
        _refresh_checklists(db)                              # y el checklist de inventario de cada evento (para consultarlo en el quiosco aunque después se pierda internet)
        res = [upload_event(db, ev, force=force) for ev in synced_events(db)]
        return {"configured": True, "events": len(res), "failed": sum(1 for r in res if not r["ok"]), "pending": sum(r["pending"] for r in res)}
    finally:
        _run_lock.release()


def release_event(db: Session, event: Event) -> dict:
    """«Pasar a internet» desde el servidor local: sube TODO y, solo si no quedó nada pendiente, pide a la nube liberar el evento. Si algo falla el evento NO se libera."""
    out = upload_event(db, event, force=True)
    if not out["ok"] or out["pending"] != 0:
        return {"ok": False, "error": out.get("error") or "Todavía hay datos pendientes de subir", "pending": out["pending"]}
    local_only = local_only_changes(db, event)
    if local_only and not allow_local_only_loss():
        detail = ", ".join(f"{n} {label}" for label, n in local_only.items())
        return {"ok": False, "pending": 0, "local_only": local_only,
                "error": f"No se puede pasar a internet: en este servidor hay datos que todavía no se suben a la nube ({detail}). "
                         "Si se libera ahora se perderían. Avise a soporte antes de liberar este evento."}
    try:
        _call("POST", f"/api/node/events/{event.cloud_event_id}/release", {"pending": 0})
    except SyncError as e:
        event.sync_error = str(e)[:300]
        db.commit()
        return {"ok": False, "error": str(e), "pending": 0}
    event.cloud_event_id = None                      # la copia local queda inerte: el evento sigue en la nube
    event.sync_error = None
    db.commit()
    return {"ok": True, "pending": 0}


# ------------------------------------------------------------------------------------------------ reloj (solo en el servidor local)
_thread = {"t": None, "stop": threading.Event()}


def _loop() -> None:
    from app.database import SessionLocal
    stop = _thread["stop"]
    stop.wait(60)                                         # deja arrancar la aplicación
    while not stop.is_set():
        try:
            cloud_ping()                                  # llave de producto: si la deshabilitaron, la nube responde 403 y este servidor se cierra (app/server_lock.py)
        except Exception:                                 # noqa: BLE001 — sin internet no pasa nada: sigue trabajando
            log.debug("ping a la nube falló", exc_info=True)
        try:
            with SessionLocal() as db:
                upload_all(db)
        except Exception:                                 # el reloj nunca se cae por un error de un ciclo
            log.exception("ciclo de subida falló")
        try:
            from app import local_update
            with SessionLocal() as db:
                res = local_update.auto_update(db)
            if res == "pending":
                log.info("actualización automática solicitada")
        except Exception:
            log.exception("actualización automática falló")
        waited = 0                                        # entre ciclos completos, el checklist de inventario se pone al día cada ~5 min (liviano; sin internet no hace nada)
        while not stop.is_set() and waited < interval_minutes() * 60:
            step = min(300, interval_minutes() * 60 - waited)
            if stop.wait(step):
                break
            waited += step
            if waited < interval_minutes() * 60:
                try:
                    with SessionLocal() as db:
                        _refresh_checklists(db)
                except Exception:                         # noqa: BLE001
                    log.debug("refresco del checklist falló", exc_info=True)


_shared = {"t": None, "backoff": {}}


def shared_events_now(db: Session) -> list:
    """Eventos compartidos que hay que mantener al día AHORA: bajados de la nube, compartidos y «En proceso» (fuera de eso no se consulta la nube: la base de la nube puede dormir)."""
    return db.query(Event).filter(Event.cloud_event_id.isnot(None), Event.local_shared.is_(True), Event.status == "en_proceso").order_by(Event.id).all()


def _shared_loop() -> None:
    from app.database import SessionLocal
    stop = _thread["stop"]
    stop.wait(30)
    while not stop.is_set():
        if not _run_lock.acquire(blocking=False):          # el ciclo largo (30 min) está subiendo: no se pisan las marcas de agua
            stop.wait(shared_seconds())
            continue
        try:
            with SessionLocal() as db:
                now = utcnow()
                for ev in shared_events_now(db):
                    until = _shared["backoff"].get(ev.id)
                    if until and now < until:
                        continue
                    out = sync_shared(db, ev)
                    _shared["backoff"][ev.id] = None if out["ok"] else now + timedelta(seconds=60)          # sin red: reintenta en un minuto, no cada 15 s
        except Exception:                                 # noqa: BLE001 — el reloj nunca se cae
            log.exception("ciclo de evento compartido falló")
        finally:
            _run_lock.release()
        stop.wait(shared_seconds())


def start() -> bool:
    """Arranca el reloj si este servidor es local y está configurado (token y PRODUCTION_URL). En la nube: no hace nada."""
    if not configured() or _thread["t"] is not None:
        return False
    _thread["stop"].clear()
    t = threading.Thread(target=_loop, name="node-upload", daemon=True)
    _thread["t"] = t
    t.start()
    s2 = threading.Thread(target=_shared_loop, name="node-shared", daemon=True)
    _shared["t"] = s2
    s2.start()
    log.info("subida automática al servidor de producción cada %s min (eventos compartidos: cada %s s)", interval_minutes(), shared_seconds())
    return True


def stop() -> None:
    _thread["stop"].set()
    _thread["t"] = None
    _shared["t"] = None
