"""Alerta de borrado masivo (Fase 9-A, 9-nov-2026): si una acción borra muchas filas importantes de golpe, o una misma cuenta acumula muchas en pocos minutos, sale un correo YA.

Se detecta al momento de borrar, dentro de la misma transacción (nada de consultas periódicas: Neon debe poder apagarse):
  · `after_flush` cuenta los objetos borrados con `db.delete(...)`; `after_bulk_delete` cuenta los `query.delete()`.
  · `before_commit` decide: ≥ `per_action` filas en una sola acción, o ≥ `window_count` en `window_minutes` (la suma por cuenta sale de `mass_delete_log`, que solo se consulta cuando la acción borró ≥ 10 filas).
  · La alerta (historial + correos por la cola + campana) entra en la MISMA transacción: si el borrado se revierte, no hay alerta. `after_commit` despierta la cola.
La purga programada de retención y la de un evento finalizado son esperadas: usan `expected(db)` y no alertan. El correo NO lleva datos de asistentes: quién (usuario y rol), qué, cuántas, cuándo y qué evento.
Límite honesto: los `DELETE` escritos a mano con `text()` no se cuentan (en el código solo los hace la supresión de UNA persona y la purga esperada).
"""
import json
import logging
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event as sa_event
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import jobs
from app.models import AlertRecipient, AppSetting, MassDeleteLog, SystemAlert
from app.timeutil import utcnow

log = logging.getLogger(__name__)
SETTING_KEY = "alert_mass_delete"
DEFAULTS = {"enabled": True, "per_action": 50, "window_count": 200, "window_minutes": 10}
LIMITS = {"per_action": (5, 100000), "window_count": (10, 1000000), "window_minutes": (1, 60)}
EVALUATE_FROM = 10                      # una acción que borra menos de esto no consulta nada
LABELS = {"Event": "eventos", "WebForm": "formularios", "FormSubmission": "inscripciones", "EventAttendee": "registros de asistentes",
          "User": "personas", "AccessLog": "registros de acceso", "EventDocument": "archivos de evento", "StaffUser": "cuentas del personal"}
MAIL_KIND = "system_alert_mail"
_INFO = "md_state"


# ------------------------------------------------------------------ configuración (pura salvo la lectura)
def clean_settings(data: dict) -> dict:
    out = dict(DEFAULTS)
    for key, (low, high) in LIMITS.items():
        try:
            out[key] = min(high, max(low, int(data.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError):
            pass
    out["enabled"] = bool(data.get("enabled", DEFAULTS["enabled"]))
    return out


def get_settings(db: Session) -> dict:
    row = db.get(AppSetting, SETTING_KEY)
    try:
        return clean_settings(json.loads(row.value)) if row is not None and row.value else dict(DEFAULTS)
    except ValueError:
        return dict(DEFAULTS)


def save_settings(db: Session, data: dict) -> dict:
    clean = clean_settings(data)
    row = db.get(AppSetting, SETTING_KEY)
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=json.dumps(clean), updated_at=utcnow()))
    else:
        row.value, row.updated_at = json.dumps(clean), utcnow()
    return clean


def decide(rows_now: int, rows_window: int, cfg: dict) -> str:
    """'' = no alerta; 'action' = una sola acción grande; 'window' = acumulado de la cuenta en la ventana."""
    if not cfg.get("enabled"):
        return ""
    if rows_now >= cfg["per_action"]:
        return "action"
    if rows_window >= cfg["window_count"]:
        return "window"
    return ""


# ------------------------------------------------------------------ contexto de la sesión
def set_actor(db: Session, staff) -> None:
    db.info["md_actor"] = (getattr(staff, "id", None), getattr(staff, "username", None), getattr(staff, "role", None))


@contextmanager
def expected(db: Session):
    """Borrados esperados (purga de retención): no alertan."""
    db.info["md_expected"] = db.info.get("md_expected", 0) + 1
    try:
        yield
    finally:
        db.info["md_expected"] -= 1


def expected_call(fn):
    """Decorador para funciones `fn(db, ...)` cuyos borrados grandes son lo normal (purga de retención)."""
    import functools

    @functools.wraps(fn)
    def wrapper(db, *args, **kwargs):
        with expected(db):
            return fn(db, *args, **kwargs)
    return wrapper


def _state(session: Session) -> dict:
    return session.info.setdefault(_INFO, {"counts": {}, "events": {}, "event_names": {}, "alerted": False, "busy": False})


def _note(session: Session, cls_name: str, n: int, event_id=None, event_name=None) -> None:
    if cls_name not in LABELS or n <= 0 or session.info.get("md_expected"):
        return
    st = _state(session)
    st["counts"][cls_name] = st["counts"].get(cls_name, 0) + n
    if event_id is not None:
        st["events"][event_id] = st["events"].get(event_id, 0) + n
        if event_name:
            st["event_names"][event_id] = event_name


def _on_after_flush(session, flush_context) -> None:
    if session.info.get(_INFO, {}).get("busy") or not session.deleted:
        return
    for obj in list(session.deleted):
        name = type(obj).__name__
        if name not in LABELS:
            continue
        if name == "Event":
            _note(session, name, 1, getattr(obj, "id", None), getattr(obj, "name", None))
        else:
            _note(session, name, 1, getattr(obj, "event_id", None))


def _on_bulk_delete(delete_context) -> None:
    try:
        name = delete_context.mapper.class_.__name__
        n = int(delete_context.result.rowcount or 0)
    except Exception:                                                # un contador que falla nunca debe romper el borrado
        return
    if name in LABELS and n > 0:
        _note(delete_context.session, name, n)


def _reset(session) -> None:
    session.info.pop(_INFO, None)


def _actor(session) -> tuple:
    return session.info.get("md_actor") or (None, None, None)


def _event_of(st: dict) -> tuple:
    if not st["events"]:
        return None, None
    event_id = max(st["events"], key=st["events"].get)
    return event_id, st["event_names"].get(event_id)


def _on_before_commit(session) -> None:
    st = session.info.get(_INFO)
    if not st or st["busy"] or sum(st["counts"].values()) < EVALUATE_FROM:
        return
    st["busy"] = True
    try:
        _evaluate(session, st)
    except Exception:                                                # la alerta es un aviso: nunca puede impedir ni deshacer lo que la persona hizo
        log.exception("alerta de borrado masivo: no se pudo evaluar")
        session.info.pop(_INFO, None)
    finally:
        if _INFO in session.info:
            session.info[_INFO]["busy"] = False


def _evaluate(session: Session, st: dict) -> None:
    cfg = get_settings(session)
    if not cfg["enabled"]:
        return
    total = sum(st["counts"].values())
    actor_id, username, role = _actor(session)
    event_id, event_name = _event_of(st)
    now = utcnow()
    top = max(st["counts"], key=st["counts"].get)
    session.add(MassDeleteLog(created_at=now, actor_id=actor_id, label=top, rows=total, event_id=event_id))
    session.flush()
    since = now - timedelta(minutes=cfg["window_minutes"])
    q = session.query(func.coalesce(func.sum(MassDeleteLog.rows), 0)).filter(MassDeleteLog.created_at >= since)
    q = q.filter(MassDeleteLog.actor_id == actor_id) if actor_id is not None else q.filter(MassDeleteLog.actor_id.is_(None))
    why = decide(total, int(q.scalar() or 0), cfg)
    if not why:
        return
    detail = ", ".join(f"{n} {LABELS[k]}" for k, n in sorted(st["counts"].items(), key=lambda kv: -kv[1]))
    who = f"{username} ({role})" if username else "el sistema (sin una cuenta identificada)"
    where = f" Evento: {event_name} (n.° {event_id})." if event_id and event_name else (f" Evento n.° {event_id}." if event_id else "")
    title = f"Alerta: borrado masivo ({total} registros)"
    body = (f"{who} borró {total} registros de golpe: {detail}.{where} Fecha y hora (Bogotá): {_bogota(now)}. "
            f"Si no fue usted o no era esperado, revise de inmediato: cambie la contraseña de esa cuenta y avise a soporte.")
    if why == "window":
        body = f"En los últimos {cfg['window_minutes']} min se acumularon borrados grandes de esta cuenta. " + body
    bucket = int(now.timestamp() // (cfg["window_minutes"] * 60))
    dedupe = f"mass:{actor_id}:{event_id}:{top}:{bucket}"[:160]
    if session.query(SystemAlert.id).filter(SystemAlert.dedupe_key == dedupe).first():
        return
    alert = SystemAlert(kind="mass_delete", title=title, body=body, event_id=event_id, actor_id=actor_id, actor_label=(username or "sistema")[:120], dedupe_key=dedupe, created_at=now)
    session.add(alert)
    session.flush()
    deliver(session, alert)
    st["alerted"] = True


def _bogota(moment) -> str:
    return (moment - timedelta(hours=5)).strftime("%d/%m/%Y %H:%M")


def deliver(db: Session, alert: SystemAlert, *, only_emails=None, force: bool = False) -> int:
    """Encola un correo por cada destinatario activo (y avisa a la campana de las cuentas). No confirma. Devuelve cuántos destinatarios."""
    from app import notifications
    from app.staff_credentials import valid_email
    sent, staff_ids = 0, []
    for r in db.query(AlertRecipient).filter(AlertRecipient.active == True).all():          # noqa: E712
        if r.kind == "email" and valid_email(r.email):
            if only_emails is not None and r.email.lower() not in only_emails:
                continue
            jobs.enqueue(db, MAIL_KIND, {"alert_id": int(alert.id), "email": r.email.strip()}, max_attempts=4,
                         dedupe_key=f"{MAIL_KIND}:{alert.id}:{r.email.strip().lower()}" + (f":{int(utcnow().timestamp())}" if force else ""))
            sent += 1
        elif r.kind == "staff" and r.staff_user_id and only_emails is None:
            staff_ids.append(r.staff_user_id)
    if staff_ids:
        sent += notifications.notify(db, staff_ids, kind="system_alert", title=alert.title, body=alert.body, event_id=alert.event_id, dedupe_key=f"sysalert:{alert.id}")
    return sent


@jobs.handler(MAIL_KIND)
def run_mail(payload: dict) -> None:
    from app import notifications
    from app.database import SessionLocal
    from app.mailer import send_mail
    with SessionLocal() as db:
        alert = db.get(SystemAlert, int(payload["alert_id"]))
        if alert is None or not payload.get("email"):
            return
        mail = notifications.render_mail(alert.title, alert.body)
        result = send_mail(payload["email"], mail["subject"], mail["text"], html=mail["html"])
        if not result.get("sent"):
            if "quedó guardado" in str(result.get("detail")):
                log.warning("alerta del sistema: el correo no está configurado; quedó guardado")
                return
            raise RuntimeError("no se pudo enviar la alerta del sistema")


def _on_after_commit(session) -> None:
    st = session.info.get(_INFO)
    alerted = bool(st and st.get("alerted"))
    _reset(session)
    if alerted:
        try:
            jobs.kick()
        except Exception:
            log.exception("alerta de borrado masivo: no se pudo despertar la cola")


_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    sa_event.listen(Session, "after_flush", _on_after_flush)
    sa_event.listen(Session, "after_bulk_delete", _on_bulk_delete)
    sa_event.listen(Session, "before_commit", _on_before_commit)
    sa_event.listen(Session, "after_commit", _on_after_commit)
    sa_event.listen(Session, "after_rollback", _reset)


install()
