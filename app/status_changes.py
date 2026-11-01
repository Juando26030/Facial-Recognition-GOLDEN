"""Retroceso de un evento «en curso» -> «creado» (pedido B) y la ventana en que los quioscos sin red todavía pueden sincronizar lo que registraron ANTES del cambio.

Un quiosco sin conexión no se entera del retroceso: sigue guardando ingresos, consentimientos y altas en su bandeja. Al volver la red los envía por `access-logs/sync`, `outbox/sync` y
`consents`, que antes respondían 403 (se perdían o quedaban atascados). Regla (aprobada por Juan David, 1-nov-2026):
  * durante `SYNC_AFTER_REVERT_DAYS` (7) días desde el retroceso, un digitador/cliente autorizado puede sincronizar aunque el evento esté en «creado»;
  * solo se guardan registros anteriores al retroceso (la hora la pone el dispositivo; `CLOCK_SKEW_S` de tolerancia, la misma que ya admite la sincronización hacia el futuro): los
    posteriores se devuelven como `unknown` con `reason: "after_revert"` (el quiosco los manda a su cola de revisión; no se pierden ni se guardan);
  * un registro SIN hora válida dentro de la ventana se acepta (perderlo es peor) pero queda marcado como dudoso (`access_logs.doubtful_reason = "sin_hora_valida"`) y se cuenta en la respuesta;
  * los consentimientos son pruebas legales de la PERSONA: se guardan siempre dentro de la ventana, los posteriores solo se cuentan (`after_revert`); nunca se descartan.
Nada de esto cambia con el evento en proceso: sin retroceso, `revert_info` devuelve None."""
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Event, EventStatusChange
from app.timeutil import utcnow

SYNC_AFTER_REVERT = timedelta(days=int(os.getenv("SYNC_AFTER_REVERT_DAYS", "7")))
CLOCK_SKEW_S = 300
SYNC_MAX_AGE_S = 30 * 24 * 3600          # igual que `SYNC_MAX_AGE` de api.py: una hora de más de 30 días atrás no es creíble
DOUBTFUL = "sin_hora_valida"
AFTER_REVERT_DETAIL = "Este registro se hizo después de que el evento volvió a «Creado»: no se guardó. Revísalo con quien administra el evento."


def revert_info(db: Session, event: Event) -> Optional[tuple]:
    """(momento del retroceso, ¿la ventana de sincronización sigue abierta?) si el evento está en «creado» tras un retroceso «en curso» -> «creado»; si no, None."""
    if event.status != "creado":
        return None
    last = (db.query(EventStatusChange).filter(EventStatusChange.event_id == event.id, EventStatusChange.from_status == "en_proceso", EventStatusChange.to_status == "creado")
            .order_by(EventStatusChange.at.desc(), EventStatusChange.id.desc()).first())
    if last is None:
        return None
    return last.at, utcnow() - last.at <= SYNC_AFTER_REVERT


def parse_utc(raw) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None) if raw else None
    except (TypeError, ValueError):
        return None


def classify(raw, now: datetime, reverted_at: Optional[datetime]) -> tuple:
    """(veredicto, hora a guardar) de un registro del dispositivo. Veredictos: `ok`, `no_hour` (sin hora válida: la hora a guardar es la del servidor) y, solo con retroceso, `after`.
    Sin retroceso el veredicto es siempre `ok` y la hora es la misma que se usaba antes (la del dispositivo si es creíble, si no la del servidor)."""
    parsed = parse_utc(raw)
    valid = parsed is not None and now.timestamp() - SYNC_MAX_AGE_S <= parsed.timestamp() <= now.timestamp() + CLOCK_SKEW_S
    when = parsed if valid else now
    if reverted_at is None:
        return "ok", when
    if not valid:
        return "no_hour", now
    if parsed.timestamp() > reverted_at.timestamp() + CLOCK_SKEW_S:
        return "after", now
    return "ok", when
