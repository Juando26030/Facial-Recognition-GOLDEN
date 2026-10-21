"""Llamadas a la API de Cloud Run con las credenciales del propio servicio/Job (sin librería extra: `google-auth` ya viene con Cloud Storage).

  run_job(nombre, args)            lanza una ejecución de un Job con otros argumentos (carga masiva, tareas de operación).
  min_instances(servicio)          instancias mínimas a nivel de servicio (no crea revisión nueva).
  set_min_instances(servicio, n)   las cambia; lo usa el precalentamiento (app/warmup.py).

`nombre`/`servicio` son rutas completas: projects/<p>/locations/<r>/jobs/<j> o .../services/<s>."""
API = "https://run.googleapis.com/v2/"
_session = None


def _http():
    global _session
    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(creds)
    return _session


def run_job(name: str, args: list) -> None:
    """Necesita run.jobs.runWithOverrides sobre ese Job (rol run.jobsExecutorWithOverrides)."""
    resp = _http().post(f"{API}{name}:run", json={"overrides": {"containerOverrides": [{"args": args}]}}, timeout=30)
    resp.raise_for_status()


def min_instances(service: str) -> int:
    resp = _http().get(f"{API}{service}", timeout=30)
    resp.raise_for_status()
    return int((resp.json().get("scaling") or {}).get("minInstanceCount") or 0)


def set_min_instances(service: str, count: int) -> None:
    """Necesita run.services.update sobre ese servicio (rol run.developer acotado al servicio)."""
    resp = _http().patch(f"{API}{service}", params={"updateMask": "scaling.minInstanceCount"},
                         json={"scaling": {"minInstanceCount": count}}, timeout=60)
    resp.raise_for_status()
