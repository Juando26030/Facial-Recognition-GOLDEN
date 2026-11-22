"""Bloqueo del servidor LOCAL cuando un administrador deshabilita su llave de producto (20-nov-2026).

Sin internet el servidor sigue trabajando (un evento no se corta por esto). En cuanto la nube responde 403 con el texto fijo de `server_keys.DISABLED_DETAIL`, se escribe `SERVER_DISABLED=1`
en config\\local.env y la aplicación entera queda cerrada (middleware de app/main.py). No hay forma de reabrirla desde la app: hace falta una llave nueva y reinstalar.

PLAZO DE GRACIA (seguridad 22-nov-2026, 04 #6): el bloqueo de arriba solo llega si el servidor habla con la nube. Para un equipo perdido que nunca vuelve a conectarse, o cuyo token
fue revocado (401, botón «Revocar»), este módulo calcula además un ESTADO de gracia (`grace_state()`):
  ok        todo normal
  warn      aviso: faltan pocos días para el límite sin nube, o la nube ya no reconoce a este servidor (menos de REVOKED_HOURS)
  readonly  SOLO LECTURA con aviso: `LOCAL_GRACE_DAYS` días (14 por defecto; 0 = apagado) sin una respuesta válida de la nube, o token revocado confirmado
            (REVOKED_PINGS respuestas 401 seguidas) desde hace más de REVOKED_HOURS
Nunca se pasa a solo lectura el mismo día: sin internet la puerta sigue con aviso (decisión de Juan David, 20-nov-2026). Volver a hablar con la nube (cualquier respuesta válida) lo
restablece solo. Las marcas viven en config\\local.env (LOCAL_CLOUD_OK_AT, LOCAL_CLOUD_401_AT, LOCAL_CLOUD_401_N): las comparten los procesos del servidor.
OJO: este módulo CALCULA el estado y da la regla (`write_blocked`); quien lo APLICA es el middleware de app/main.py y el aviso de las plantillas, que todavía NO lo usan
(docs/revision_2026-11-22/12_seguridad_correcciones.md, pendiente 2). Hasta entonces el servidor se comporta exactamente como antes.
Módulo sin dependencias de la app (solo lee/escribe local.env)."""
import os
import re
import time

from app import local_env, server_keys

LOCKED_MSG = "Este servidor local fue deshabilitado por un administrador de Golden. Ya no se puede usar; para instalar de nuevo hace falta una llave de producto nueva."
_cache = {"at": 0.0, "locked": False}
CHECK_EVERY = 10.0


def _read_flag() -> bool:
    try:
        with open(local_env.env_file(), encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*SERVER_DISABLED\s*=\s*(.*?)\s*$", line)
                if m and m.group(1).strip().lower() in ("1", "true", "yes", "si"):
                    return True
    except OSError:
        pass
    return False


def is_locked() -> bool:
    """¿Este servidor local está deshabilitado? Mira la variable del proceso y, cada 10 s, el archivo (los varios procesos del servidor se enteran entre sí)."""
    if (os.getenv("SERVER_DISABLED") or "").strip().lower() in ("1", "true", "yes", "si"):
        return True
    now = time.monotonic()
    if now - _cache["at"] > CHECK_EVERY:
        _cache["at"] = now
        _cache["locked"] = _read_flag()
    return _cache["locked"]


def lock() -> None:
    """Marca este servidor como deshabilitado (en el archivo y en este proceso)."""
    os.environ["SERVER_DISABLED"] = "1"
    _cache.update(at=time.monotonic(), locked=True)
    try:
        local_env.save({"SERVER_DISABLED": "1"})
    except OSError:
        pass


def note_cloud_error(status, detail) -> None:
    """Para quien habla con la nube: si la respuesta es «servidor deshabilitado», bloquea."""
    if status == 403 and detail == server_keys.DISABLED_DETAIL:
        lock()
    elif status == 401:                                       # token revocado (o ausente): cuenta para el plazo de gracia; NO bloquea
        _note_unauthorized()


# ------------------------------------------------------------------------------------------------ plazo de gracia sin nube (04 #6)
GRACE_DAYS_DEFAULT = 14
WARN_DAYS_BEFORE = 3                 # desde cuántos días antes del límite se avisa
REVOKED_PINGS = 3                    # respuestas 401 seguidas para dar el token por revocado (una sola puede ser un error pasajero)
REVOKED_HOURS = 24                   # nunca solo lectura el mismo día
SAVE_EVERY = 3600.0                  # la marca de «última respuesta de la nube» se escribe a lo sumo una vez por hora (el evento compartido habla cada 15 s)
READONLY_MSG = ("Este servidor local está en SOLO LECTURA: {why}. Se puede consultar, pero no registrar ni cambiar nada hasta que vuelva a conectarse a internet "
                "y la nube lo reconozca. Si el problema sigue, avisa a un administrador de Golden.")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
# Lo que SIEMPRE se deja escribir en solo lectura: entrar/salir, y todo lo que sirve para volver a hablar con la nube y SUBIR lo pendiente (nunca se retienen datos en el portátil).
READONLY_ALLOW_PREFIXES = ("/static", "/health", "/login", "/logout", "/api/local/", "/api/node-sync/")
_grace = {"at": 0.0, "marks": None, "saved_ok": 0.0, "dirty_401": True}          # dirty_401: puede haber un 401 anotado (al arrancar no se sabe) → el siguiente «ok» sí se escribe


def grace_days() -> int:
    try:
        return max(0, int((os.getenv("LOCAL_GRACE_DAYS") or str(GRACE_DAYS_DEFAULT)).strip()))
    except ValueError:
        return GRACE_DAYS_DEFAULT


def grace_decision(now_ts: float, last_ok_ts, first_401_ts, n_401: int, days: int) -> dict:
    """Regla PURA. {state: ok|warn|readonly, reason: None|offline|revoked, days_offline, days_left, message}."""
    out = {"state": "ok", "reason": None, "days_offline": None, "days_left": None, "message": ""}
    if days <= 0:
        return out
    if first_401_ts and n_401 >= REVOKED_PINGS:
        hours = max(0.0, now_ts - float(first_401_ts)) / 3600.0
        out["reason"] = "revoked"
        if hours >= REVOKED_HOURS:
            out.update(state="readonly", message=READONLY_MSG.format(why="la nube ya no reconoce a este servidor (su acceso fue revocado)"))
        else:
            out.update(state="warn", message="La nube ya no reconoce a este servidor (su acceso fue revocado). Sigue funcionando hoy; si no se corrige, mañana quedará en solo lectura. Avisa a un administrador de Golden.")
        return out
    if not last_ok_ts:
        return out                                            # sin marca todavía: el reloj empieza cuando `grace_state` la escribe
    offline = max(0.0, now_ts - float(last_ok_ts)) / 86400.0
    out["days_offline"], out["days_left"] = int(offline), max(0, days - int(offline))
    if offline >= days:
        out.update(state="readonly", reason="offline", message=READONLY_MSG.format(why=f"lleva {int(offline)} días sin conectarse a la nube (el límite es {days})"))
    elif offline >= max(1, days - WARN_DAYS_BEFORE):
        left = out["days_left"]
        out.update(state="warn", reason="offline", message=f"Este servidor lleva {int(offline)} días sin conectarse a la nube. Conéctalo a internet: en {left} día{'s' if left != 1 else ''} quedará en solo lectura.")
    return out


def _read_marks() -> dict:
    marks = {}
    try:
        with open(local_env.env_file(), encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^\s*(LOCAL_CLOUD_OK_AT|LOCAL_CLOUD_401_AT|LOCAL_CLOUD_401_N)\s*=\s*(\d+)\s*$", line)
                if m:
                    marks[m.group(1)] = int(m.group(2))
    except OSError:
        pass
    return marks


def _save_marks(values: dict) -> None:
    try:
        local_env.save(values)
    except OSError:
        pass
    _grace.update(at=0.0, marks=None)


def note_cloud_ok() -> None:
    """La nube respondió bien con el token de este servidor: reinicia el plazo (y borra un 401 anterior)."""
    now = time.time()
    if not _grace["dirty_401"] and now - _grace["saved_ok"] < SAVE_EVERY:
        return
    _grace.update(saved_ok=now, dirty_401=False)
    _save_marks({"LOCAL_CLOUD_OK_AT": int(now), "LOCAL_CLOUD_401_AT": 0, "LOCAL_CLOUD_401_N": 0})


def _note_unauthorized() -> None:
    _grace["dirty_401"] = True
    marks = _read_marks()
    n = int(marks.get("LOCAL_CLOUD_401_N") or 0)
    if n >= REVOKED_PINGS:
        return                                                # ya confirmado: no se escribe más
    _save_marks({"LOCAL_CLOUD_401_AT": int(marks.get("LOCAL_CLOUD_401_AT") or 0) or int(time.time()), "LOCAL_CLOUD_401_N": n + 1})


def grace_state(now_ts=None) -> dict:
    """Estado de gracia de ESTE servidor (ver el encabezado). Lee las marcas del archivo a lo sumo cada CHECK_EVERY segundos. La primera vez (instalación anterior a esta versión,
    sin marcas) el reloj empieza AHORA: actualizar nunca deja un servidor en solo lectura de golpe."""
    days = grace_days()
    if days <= 0:
        return grace_decision(0, None, None, 0, 0)
    mono = time.monotonic()
    if _grace["marks"] is None or mono - _grace["at"] > CHECK_EVERY:
        _grace.update(at=mono, marks=_read_marks())
    marks = _grace["marks"]
    now = float(now_ts if now_ts is not None else time.time())
    if not marks.get("LOCAL_CLOUD_OK_AT"):
        _save_marks({"LOCAL_CLOUD_OK_AT": int(now)})
        marks = {**marks, "LOCAL_CLOUD_OK_AT": int(now)}
    return grace_decision(now, marks.get("LOCAL_CLOUD_OK_AT"), marks.get("LOCAL_CLOUD_401_AT"), int(marks.get("LOCAL_CLOUD_401_N") or 0), days)


def write_blocked(method: str, path: str, state: str) -> bool:
    """Regla PURA para el middleware: en `readonly` no pasa ninguna escritura, salvo entrar/salir y lo que sirve para reconectar y subir lo pendiente."""
    if state != "readonly" or (method or "").upper() not in WRITE_METHODS:
        return False
    return not any(path == p.rstrip("/") or path.startswith(p) for p in READONLY_ALLOW_PREFIXES)
