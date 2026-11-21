"""Subida del servidor LOCAL hacia la nube (Fase 6, docs/FASE_6_SERVIDOR_LOCAL.md). Solo corre con LOCAL_SERVER=1 (en la nube no hace nada y no toca la base).

Cada ~NODE_UPLOAD_MINUTES (30) y cuando alguien lo pide, el servidor local sube lo que tenga de cada evento que bajó de la nube (`Event.cloud_event_id`):
  1. personas dadas de alta aquí (origen manual / autoregistro)  -> POST /api/node/events/{id}/outbox      (`create_person`, idempotente por op_id)
  2. ingresos de personas que ya estaban (AccessLog «Existente») -> POST /api/node/events/{id}/access-logs (idempotente por client_id)
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
from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import local_env, peer_changes, versioning
from app.models import AccessLog, Event, EventAttendee, PersonChange, PrintLog, User
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


def _call(method: str, path: str, body: Optional[dict] = None) -> dict:
    url = versioning.production_url()
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.0.0.1")):
        raise SyncError("PRODUCTION_URL debe ser https")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method, headers=_headers())
    from app.cloud_client import open_no_redirect
    try:
        with open_no_redirect(req, timeout=HTTP_TIMEOUT) as resp:      # F5-9 A-10: sin redirecciones (el token no viaja a otra dirección)
            return json.loads(resp.read(2_000_000).decode("utf-8") or "{}")
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


def pending_counts(db: Session, event: Event) -> dict:
    persons = _persons_query(db, event).count()
    logs = _logs_query(db, event).filter(AccessLog.record_type == LOG_TYPE).count()
    prints = _prints_query(db, event).count()
    changes = _changes_query(db, event).count()
    return {"persons": persons, "logs": logs, "prints": prints, "changes": changes, "total": persons + logs + prints + changes}


# Lo que se hace en el servidor local y TODAVÍA NO SUBE a la nube (la subida solo lleva personas nuevas e ingresos). Mientras exista algo así,
# «Pasar a internet» NO libera el evento: se perdería sin aviso (revisión 9-nov-2026, docs/FASE_6_SERVIDOR_LOCAL.md). Nombres fijos (no vienen del usuario).
LOCAL_ONLY = (
    ("inventory_deliveries", "delivered_at", "entregas de inventario"),
    ("event_inventory_items", "updated_at", "cambios del inventario del evento"),
    ("area_movements", "timestamp", "movimientos de áreas"),
    ("roulette_draws", "created_at", "sorteos de la ruleta"),
    ("queue_turns", "created_at", "turnos"),
    ("queue_calls", "called_at", "llamados de turnos"),
    ("exhibitor_leads", "scanned_at", "contactos de expositores"),
    ("web_acceptances", "created_at", "aceptaciones y firmas"),
    ("audit_consent_logs", "consent_timestamp_utc", "autorizaciones de datos"),
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


def pull_event(db: Session, event: Event, max_pages: int = 20) -> dict:
    """Evento compartido: baja de la nube lo que hicieron los OTROS servidores desde el cursor y lo aplica aquí (sin duplicar). Lanza SyncError si no hay red."""
    total = {"persons": 0, "access_logs": 0, "print_logs": 0, "person_changes": 0}
    cur = peer_changes.clean_cursor(event.peer_cursor)
    for _ in range(max_pages):
        q = "&".join(f"{k}={cur[k]}" for k in peer_changes.KEYS)
        data = _call("GET", f"/api/node/events/{event.cloud_event_id}/changes?{q}")
        added = peer_changes.apply_changes(db, event, data)
        for k, v in added.items():
            total[k] += v
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
        if event.local_shared:
            pull_event(db, event)                # compartido: de paso baja lo de los demás servidores
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
