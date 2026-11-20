"""Chequeo semanal de salud de la base (Neon) con aviso y reinicio del cómputo, SIN borrar datos (20-nov-2026).

Por qué existe: una vez la plataforma se «colapsó» (había que reiniciar el cómputo de Neon para que la página volviera) porque un botón cargaba miles de registros por clic y se pulsó varias veces:
muchas conexiones y consultas largas a la vez. Aquí se mira lo que anuncia ese tipo de colapso y, si es grave, se avisa y se reinicia el cómputo (Neon vuelve en segundos; los datos no se tocan).

Corre UNA vez por semana (domingo, OPS_HEALTH_HOUR, por defecto las 6 a. m. hora local) dentro del Job de operaciones, o a mano: `python -m app.ops_runner db-health`.
Semanal a propósito: nada frecuente puede tocar la base (mantendría a Neon despierta todo el mes; ver app/warmup.py).

Qué mira (todo con UNA conexión corta, solo números): tamaño de la base, conexiones usadas frente al máximo, conexiones «idle in transaction» viejas, consultas largas y consultas bloqueadas por candados.
Niveles: `ok` · `warn` (se avisa) · `critical` (se avisa y se REINICIA el cómputo si no hay un evento en proceso; con evento en proceso solo se avisa y se pide decidir a mano).
Si no puede ni conectarse a la base, es `critical` (justo el colapso que se quiere detectar) y se reinicia.

Variables (todas opcionales): NEON_API_KEY + NEON_PROJECT_ID + NEON_ENDPOINT_ID (las mismas del precalentamiento; sin ellas solo se avisa), DB_HEALTH_RESTART (1; 0 = nunca reiniciar),
DB_HEALTH_SIZE_WARN_GB (6), DB_HEALTH_SIZE_CRIT_GB (9), DB_HEALTH_CONN_WARN_PCT (60), DB_HEALTH_CONN_CRIT_PCT (85), DB_HEALTH_LONG_QUERY_S (300), DB_HEALTH_IDLE_TX_S (600), DB_HEALTH_BLOCKED_CRIT (5).
Los avisos van a los destinatarios de Configuración › Alertas del sistema (los mismos del borrado masivo) y a la campana; no llevan datos personales."""
import logging
import os
import time
from datetime import timedelta
from typing import Optional

from app.timeutil import utcnow

log = logging.getLogger("golden.db_health")

STATS_SQL = """
SELECT
  pg_database_size(current_database()),
  (SELECT setting::int FROM pg_settings WHERE name = 'max_connections'),
  (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()),
  (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'idle in transaction'
      AND now() - state_change > make_interval(secs => :idle_tx)),
  (SELECT COALESCE(max(EXTRACT(EPOCH FROM now() - query_start)), 0)::int FROM pg_stat_activity
      WHERE datname = current_database() AND state = 'active' AND pid <> pg_backend_pid()),
  (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock')
"""


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def thresholds() -> dict:
    return {"size_warn_gb": _f("DB_HEALTH_SIZE_WARN_GB", 6), "size_crit_gb": _f("DB_HEALTH_SIZE_CRIT_GB", 9),
            "conn_warn_pct": _f("DB_HEALTH_CONN_WARN_PCT", 60), "conn_crit_pct": _f("DB_HEALTH_CONN_CRIT_PCT", 85),
            "long_query_s": _f("DB_HEALTH_LONG_QUERY_S", 300), "idle_tx_s": _f("DB_HEALTH_IDLE_TX_S", 600), "blocked_crit": _f("DB_HEALTH_BLOCKED_CRIT", 5)}


def evaluate(stats: Optional[dict], th: Optional[dict] = None) -> dict:
    """Función PURA. `stats` None = no se pudo conectar. Devuelve {level: ok|warn|critical, findings: [str], restart_recommended: bool}."""
    th = th or thresholds()
    if stats is None:
        return {"level": "critical", "findings": ["La base de datos no respondió (no se pudo conectar o la consulta de salud se agotó)."], "restart_recommended": True}
    findings, level = [], "ok"

    def bump(to: str, text: str) -> None:
        nonlocal level
        findings.append(text)
        if to == "critical" or level == "ok":
            level = "critical" if to == "critical" else "warn"

    gb = stats["size_bytes"] / 1024 ** 3
    if gb >= th["size_crit_gb"]:
        bump("critical", f"La base pesa {gb:.1f} GB (límite crítico {th['size_crit_gb']:.0f} GB).")
    elif gb >= th["size_warn_gb"]:
        bump("warn", f"La base pesa {gb:.1f} GB (aviso desde {th['size_warn_gb']:.0f} GB).")
    pct = 100.0 * stats["connections"] / max(1, stats["max_connections"])
    if pct >= th["conn_crit_pct"]:
        bump("critical", f"Conexiones al {pct:.0f}% ({stats['connections']} de {stats['max_connections']}): la base está por quedarse sin conexiones.")
    elif pct >= th["conn_warn_pct"]:
        bump("warn", f"Conexiones al {pct:.0f}% ({stats['connections']} de {stats['max_connections']}).")
    if stats["blocked"] >= th["blocked_crit"]:
        bump("critical", f"{stats['blocked']} consultas esperando un candado (algo las tiene trabadas).")
    elif stats["blocked"]:
        bump("warn", f"{stats['blocked']} consulta(s) esperando un candado.")
    if stats["longest_s"] >= th["long_query_s"]:
        bump("warn", f"Hay una consulta corriendo hace {stats['longest_s']} s (más de {int(th['long_query_s'])} s).")
    if stats["idle_tx"]:
        bump("warn", f"{stats['idle_tx']} conexión(es) abiertas sin terminar su transacción hace más de {int(th['idle_tx_s'])} s.")
    return {"level": level, "findings": findings, "restart_recommended": level == "critical"}


def collect(timeout_s: int = 20) -> Optional[dict]:
    """Una conexión corta y UNA consulta. None si no se pudo (base caída, trabada o sin respuesta)."""
    from sqlalchemy import text

    from app.database import SessionLocal
    th = thresholds()
    try:
        with SessionLocal() as db:
            db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_s) * 1000}"))          # el SET LOCAL vive solo dentro de esta transacción (compatible con el pooler en modo transacción)
            row = db.execute(text(STATS_SQL), {"idle_tx": int(th["idle_tx_s"])}).one()
        return {"size_bytes": int(row[0]), "max_connections": int(row[1]), "connections": int(row[2]), "idle_tx": int(row[3]), "longest_s": int(row[4]), "blocked": int(row[5])}
    except Exception as e:  # noqa: BLE001 — cualquier fallo de conexión o de tiempo = la base no responde
        log.warning("chequeo de salud: no se pudo consultar la base (%s)", type(e).__name__)
        return None


def running_events() -> Optional[int]:
    """Eventos «en proceso» (None si no se pudo saber). Con evento en proceso NO se reinicia a ciegas."""
    from sqlalchemy import text

    from app.database import SessionLocal
    try:
        with SessionLocal() as db:
            return int(db.execute(text("SELECT count(*) FROM events WHERE status = 'en_proceso'")).scalar() or 0)
    except Exception:  # noqa: BLE001
        return None


def neon_configured() -> bool:
    return bool(os.getenv("NEON_API_KEY") and os.getenv("NEON_PROJECT_ID") and os.getenv("NEON_ENDPOINT_ID"))


def restart_compute() -> str:
    """Reinicia el cómputo de Neon por su API (no toca datos). Lanza si falla."""
    from app import warmup
    path = f"/projects/{os.environ['NEON_PROJECT_ID']}/endpoints/{os.environ['NEON_ENDPOINT_ID']}/restart"
    warmup._neon("POST", path)
    return "cómputo de Neon reiniciado"


def _wait_back(tries: int = 6, pause_s: float = 10.0) -> bool:
    for _ in range(tries):
        time.sleep(pause_s)
        if collect(timeout_s=10) is not None:
            return True
    return False


def notify(level: str, findings: list, action: str) -> int:
    """Aviso a los destinatarios de Alertas del sistema y a la campana. Devuelve a cuántos; 0 si la base aún no responde (queda en el log y en el resultado del Job)."""
    from app import mass_delete
    from app.database import SessionLocal
    from app.models import SystemAlert
    now = utcnow()
    title = {"critical": "Alerta: la base de datos estuvo en estado crítico", "warn": "Aviso: la base de datos necesita atención"}.get(level, "Chequeo de la base de datos")
    body = ("Chequeo semanal de la base de datos (Neon). " + " ".join(findings) + f" Acción: {action} "
            f"Fecha y hora (Bogotá): {mass_delete._bogota(now)}. Los datos no se tocaron.")
    try:
        with SessionLocal() as db:
            alert = SystemAlert(kind="db_health", title=title, body=body, actor_label="sistema", dedupe_key=f"dbh:{level}:{now:%Y%m%d}{now.hour // 6}", created_at=now)          # el mismo aviso, como mucho cada 6 h: si el paso se repite cada hora no llena el correo
            db.add(alert)
            db.flush()
            n = mass_delete.deliver(db, alert)
            db.commit()
            return n
    except Exception as e:  # noqa: BLE001
        log.error("chequeo de salud: no se pudo guardar el aviso (%s)", type(e).__name__)
        return 0


def run() -> str:
    """Paso del Job de operaciones. Devuelve un resumen corto; lanza si quedó crítico sin poder resolverlo (el Job sale con error y Cloud Monitoring avisa)."""
    stats = collect()
    verdict = evaluate(stats)
    level, findings = verdict["level"], verdict["findings"]
    if level == "ok":
        gb = stats["size_bytes"] / 1024 ** 3
        return f"base sana: {gb:.2f} GB, {stats['connections']}/{stats['max_connections']} conexiones"
    action = "solo aviso."
    restarted = False
    if verdict["restart_recommended"]:
        events = running_events() if stats is not None else None
        if os.getenv("DB_HEALTH_RESTART", "1").strip() in ("0", "false", "no"):
            action = "reinicio apagado por configuración (DB_HEALTH_RESTART=0): hay que reiniciar a mano en Neon."
        elif not neon_configured():
            action = "faltan NEON_API_KEY, NEON_PROJECT_ID y NEON_ENDPOINT_ID: hay que reiniciar a mano el cómputo en Neon."
        elif events:
            action = f"NO se reinició porque hay {events} evento(s) en proceso (reiniciar corta las conexiones unos segundos): decidir a mano."
        else:
            try:
                restart_compute()
                restarted = True
                back = _wait_back()
                action = "se reinició el cómputo de Neon" + (" y la base volvió a responder." if back else "; la base TODAVÍA no responde, hay que revisar en Neon.")
                if not back:
                    level = "critical"
            except Exception as e:  # noqa: BLE001
                action = f"se intentó reiniciar el cómputo pero falló ({type(e).__name__}): hay que reiniciar a mano en Neon."
    sent = notify(level, findings, action)
    summary = f"{level}: {' '.join(findings)} | {action} | avisos: {sent}"
    if level == "critical" and not (restarted and "volvió a responder" in action):
        raise RuntimeError(summary)
    return summary
