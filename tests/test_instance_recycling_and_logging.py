"""Corrida 9: reciclaje de procesos (GUNICORN_MAX_REQUESTS=0 solo en el servicio público, GUNICORN_KEEPALIVE), contrapresión fuera de «Estado del sistema» y de los errores 5xx,
`record_5xx` fuera del bucle de eventos y `is_google_infra` con caché por IP."""
import logging
import re
import runpy
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import obs, ops, security
from app.main import app
from app.models import SystemEvent
from app.routers import forms_public
from tests.test_form_backpressure import _open_form
from tests.test_forms import _person_values, _submit
from tests.test_gcloud_env_vars import BASH

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ 1) GUNICORN_MAX_REQUESTS=0 solo en el público; sobrevive al CI
def test_max_requests_zero_is_set_only_on_the_public_service_in_deploy_sh():
    deploy = (ROOT / "deploy" / "gcp" / "deploy.sh").read_text(encoding="utf8")
    lines = [ln for ln in deploy.splitlines() if ln.startswith("deploy_service \"$SVC_")]
    by_service = {re.search(r"SVC_(\w+)", ln).group(1): ln for ln in lines}
    assert set(by_service) == {"WEB", "PUBLICO", "BIOMETRIA"}
    assert "GUNICORN_MAX_REQUESTS=0" in by_service["PUBLICO"]
    assert "GUNICORN_MAX_REQUESTS" not in by_service["WEB"] and "GUNICORN_MAX_REQUESTS" not in by_service["BIOMETRIA"]       # web y biometría siguen reciclando
    common = [ln for ln in (ROOT / "deploy" / "gcp" / "env" / "common.yaml").read_text(encoding="utf8").splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in common if "GUNICORN_MAX_REQUESTS" in ln]                              # common.yaml es de los TRES servicios: aquí NO va
    workflow = (ROOT / ".github" / "workflows" / "cloudrun-deploy.yml").read_text(encoding="utf8")
    assert 'bash deploy/gcp/deploy.sh "$GOLDEN_ENV"' in workflow                                   # el workflow (staging y producción) aplica deploy.sh, que regenera el archivo de variables


@pytest.mark.skipif(BASH is None, reason="sin bash")
def test_deploy_env_file_carries_the_extra_variable_as_a_string(tmp_path):
    """Se ejecuta la función `env_file` REAL de deploy.sh (con las funciones de ayuda de nube sustituidas): el público sale con `GUNICORN_MAX_REQUESTS: "0"` en su archivo de variables
    (`--env-vars-file`), y cada despliegue de CI lo regenera."""
    deploy = (ROOT / "deploy" / "gcp" / "deploy.sh").read_text(encoding="utf8")
    body = deploy[deploy.index("env_file() {"):]
    body = body[:body.index("\n}\n") + 3]
    header = ('run_path() { echo "p/$2"; }\nsa_email() { echo sa@x; }\n'
              "GOLDEN_ENV=staging PUBLIC_BASE_URL=http://x APP_BUCKET=b APP_PREFIX=app BACKUP_BUCKET=bb QUEUE=q WEB_URL=http://w SA_INVOKER=i "
              "JOB_BULK=jb JOB_OPS=jo SVC_WEB=w SVC_PUBLICO=p SVC_BIOMETRIA=b\n")
    script = tmp_path / "t.sh"
    script.write_text(header + body + '\nenv_file "$1" APP_MODULE=m WEB_CONCURRENCY=2 GUNICORN_MAX_REQUESTS=0\n', encoding="utf8", newline="\n")
    out = tmp_path / "out.yaml"
    r = subprocess.run([BASH, str(script), str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf8", timeout=60)
    assert r.returncode == 0, r.stderr
    assert 'GUNICORN_MAX_REQUESTS: "0"' in out.read_text(encoding="utf8")


def _conf(monkeypatch, **env):
    for k in ("GUNICORN_MAX_REQUESTS", "GUNICORN_KEEPALIVE", "WEB_CONCURRENCY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return runpy.run_path(str(ROOT / "deploy" / "gunicorn.conf.py"))


def test_gunicorn_conf_keepalive_defaults_to_5_and_max_requests_zero_is_accepted(monkeypatch):
    base = _conf(monkeypatch)
    assert base["keepalive"] == 5 and base["max_requests"] == 1500 and base["max_requests_jitter"] == 300        # sin cambio de comportamiento
    assert _conf(monkeypatch, GUNICORN_KEEPALIVE="650")["keepalive"] == 650
    assert _conf(monkeypatch, GUNICORN_MAX_REQUESTS="0")["max_requests"] == 0                                      # 0 = nunca reciclar


# ------------------------------------------------------------------ 2) contrapresión: INFO y sin on_5xx; los 5xx reales siguen igual
def _mini_app(spy):
    mini = FastAPI()

    @mini.get("/busy")
    def busy():
        return JSONResponse({"busy": True}, status_code=503, headers={"Retry-After": "2", "X-Golden-Busy": "1"})

    @mini.get("/dbdown")
    def dbdown():
        return JSONResponse({"detail": "base caída"}, status_code=503, headers={"Retry-After": "3"})          # 503 REAL con Retry-After: no es contrapresión

    @mini.get("/boom")
    def boom():
        return JSONResponse({"detail": "x"}, status_code=500)

    mini.add_middleware(obs.RequestLogMiddleware, on_5xx=lambda *a: spy.append(a))
    return mini


def test_busy_503_is_logged_at_info_and_skips_on_5xx_but_real_5xx_do_not(caplog):
    spy = []
    c = TestClient(_mini_app(spy))
    with caplog.at_level(logging.INFO, logger="golden.http"):
        busy = c.get("/busy")
        c.get("/dbdown")
        c.get("/boom")
    levels = {r.getMessage().split()[1]: r.levelno for r in caplog.records if r.name == "golden.http"}
    assert levels["/busy"] == logging.INFO and levels["/dbdown"] == logging.ERROR and levels["/boom"] == logging.ERROR
    assert [a[2] for a in spy] == ["/dbdown", "/boom"]                                               # la contrapresión no llama a on_5xx
    assert busy.status_code == 503 and busy.headers["retry-after"] == "2" and "x-golden-busy" not in busy.headers       # la marca interna no sale al cliente


def test_real_busy_response_writes_no_error_row_and_a_real_5xx_does(factory, db, monkeypatch):
    from app import formsvc
    monkeypatch.setenv("FORM_MAX_LOCK_WAITERS", "1")
    ev, f = _open_form(TestClient(app, follow_redirects=False), factory)
    ops._last_5xx_write = 0.0
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    assert forms_public._enter_lock_zone()                                                          # la zona del bloqueo está llena
    try:
        r = _submit(client, ev, f, _person_values(), sid="s-busy")
    finally:
        forms_public._leave_lock_zone()
    assert r.status_code == 503 and r.json()["busy"] is True and "x-golden-busy" not in r.headers
    time.sleep(0.5)
    assert db.query(SystemEvent).filter_by(kind="error_5xx").count() == 0                           # contrapresión: ninguna fila «error_5xx»

    def boom(*a, **k):
        raise RuntimeError("falla real")

    monkeypatch.setattr(formsvc, "reserve_slot", boom)
    assert _submit(client, ev, f, {**_person_values(), "cedula": "4004"}, sid="s-real").status_code == 500
    deadline = time.time() + 10
    while db.query(SystemEvent).filter_by(kind="error_5xx").count() == 0 and time.time() < deadline:
        time.sleep(0.1)
        db.expire_all()
    assert db.query(SystemEvent).filter_by(kind="error_5xx").count() == 1                           # un 5xx real sí queda registrado


def test_record_5xx_never_blocks_the_caller_with_the_database(monkeypatch):
    """La escritura va en un hilo: aunque la base tarde, `record_5xx` (que corre en el bucle de eventos) vuelve al instante."""
    started, release = threading.Event(), threading.Event()

    def slow_write(*a, **k):
        started.set()
        release.wait(10)

    monkeypatch.setattr(ops, "record_system_event", slow_write)
    ops._last_5xx_write = 0.0
    t0 = time.time()
    fut = ops.record_5xx("rid", "GET", "/x", 500)
    assert time.time() - t0 < 0.5 and fut is not None                                              # no esperó a la escritura
    assert started.wait(5)
    assert threading.current_thread() is threading.main_thread() and not fut.done()
    release.set()
    fut.result(10)


# ------------------------------------------------------------------ 3) is_google_infra con caché por IP
def test_is_google_infra_is_cached_per_ip_and_cleared_on_reload(monkeypatch):
    import ipaddress
    monkeypatch.setattr(security, "_infra_cache", ([ipaddress.ip_network("66.102.0.0/20"), ipaddress.ip_network("2001:4860::/32")], "prueba", "prueba"))
    security._google_infra_lookup.cache_clear()
    assert security.is_google_infra("66.102.1.5") is True and security.is_google_infra("8.8.8.8") is False and security.is_google_infra("no-es-ip") is False
    assert security.is_google_infra("2001:4860:1::1") is True
    before = security._google_infra_lookup.cache_info()
    for _ in range(50):
        assert security.is_google_infra("66.102.1.5") is True
    after = security._google_infra_lookup.cache_info()
    assert after.hits - before.hits == 50 and after.misses == before.misses                        # las repeticiones no recorren la lista
    security.reload_infra()
    assert security._google_infra_lookup.cache_info().currsize == 0                                # releer la lista vacía la caché
