"""Herramientas de la prueba de carga (Fase 4): candado de destino (nunca producción) y limpieza de los datos sintéticos de staging."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from scripts.load_cfg import check_host

ROOT = Path(__file__).resolve().parent.parent

STAGING = ["golden-staging-123.web.app", "golden-web-staging-123.us-east4.run.app"]


def test_generators_refuse_production_and_mistyped_hosts_even_with_staging_in_the_name():
    ok = "https://golden-staging-123.web.app"
    assert check_host(ok, STAGING) is None and check_host("https://golden-web-staging-123.us-east4.run.app/", STAGING) is None
    for bad in ("https://app.golden-eventos.com",                        # el dominio de producción
                "https://golden-app-123.web.app",                        # el sitio de Firebase de producción (sin «staging»)
                "https://golden-web-123.us-east4.run.app",               # el run.app de producción
                "https://golden-staging-123.web.app.evil.example",       # «staging» en otro sitio del nombre
                "https://evil-staging.example.com",                      # contiene «staging» pero NO es uno de los hosts exactos
                "http://golden-staging-123.web.app",                     # sin https
                "golden-staging-123.web.app", "", "https://"):
        assert check_host(bad, STAGING) is not None, bad
    assert check_host("https://golden-staging-999.web.app", STAGING) is not None      # otro sitio de staging: tampoco (lista exacta)
    assert check_host("https://golden-eventos.example-staging.com", STAGING) is not None
    assert check_host("https://algo-staging.example", []) is None                     # sin lista exacta solo rige el primer candado (run_task exige la lista)


def test_run_task_needs_the_exact_allowed_list(monkeypatch):
    src = open("deploy/loadtest/run_task.py", encoding="utf8").read()
    assert "LOAD_ALLOWED_HOSTS" in src and "Falta LOAD_ALLOWED_HOSTS" in src and "check_host" in src
    sh = open("deploy/loadtest/run_phase4.sh", encoding="utf8").read()
    assert "LOAD_ALLOWED_HOSTS=$(allowed_hosts)" in sh and "NO es un destino de staging permitido" in sh


@pytest.fixture()
def seeded(db, monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "token-de-prueba")
    from scripts import seed_load_staging as s
    return s, s.seed(db, 30, 10)


def _fill_run(db, s, info):
    from app.models import AccessLog, FormSubmission, User, WebForm
    form = db.query(WebForm).filter_by(event_id=info["event_id"]).one()
    for i in range(5):
        db.add(FormSubmission(form_id=form.id, event_id=info["event_id"], data_json="{}", person_id=f"p{i}", sid=f"s{i}", status="confirmed"))
    uid = db.query(User).filter_by(tenant_id=s.TENANT).first().id
    for _ in range(3):
        db.add(AccessLog(tenant_id=s.TENANT, user_id=uid, record_type="Existente", event_id=info["event_id"], registration_method="tradicional"))
    db.commit()


def test_verify_reset_and_delete_all_touch_only_the_load_event(db, factory, seeded):
    s, info = seeded
    other = factory.event("en_proceso", tenant_id="acme")
    factory.person(other, "1001")
    _fill_run(db, s, info)
    v = s.verify(db)
    assert (v["capacity"], v["confirmed_submissions"], v["oversold"], v["duplicate_persons"], v["duplicate_sids"], v["access_logs_in_event"]) == (10, 5, 0, 0, 0, 3)
    r = s.reset_runs(db)
    assert r["form_submissions"] == 5 and r["access_logs"] == 3
    v = s.verify(db)
    assert v["confirmed_submissions"] == 0 and v["access_logs_in_event"] == 0
    from app.models import Event, StaffUser, Tenant, User, WebForm
    assert db.query(Event).filter_by(event_code=s.EVENT_CODE).count() == 1 and db.query(User).filter_by(tenant_id=s.TENANT).count() == 30      # se queda todo lo demás
    _fill_run(db, s, info)
    c = s.delete_all(db)
    assert c["users"] == 30 and c["staff_users"] == 1
    assert db.query(Event).filter_by(event_code=s.EVENT_CODE).count() == 0 and db.query(WebForm).filter_by(slug=s.FORM_SLUG).count() == 0
    assert db.query(User).filter_by(tenant_id=s.TENANT).count() == 0 and db.query(Tenant).filter_by(id=s.TENANT).count() == 0
    assert db.query(StaffUser).filter_by(username=s.USERNAME).count() == 0
    assert db.query(Event).filter_by(id=other.id).count() == 1 and db.query(User).filter_by(id="1001", tenant_id="acme").count() == 1       # lo de otros, intacto
    assert s.delete_all(db)["users"] == 0                                                                                                     # repetirlo no falla


def test_seed_script_refuses_to_run_outside_staging_on_neon(monkeypatch):
    from scripts import seed_load_staging as s
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x.us-east-1.aws.neon.tech/db")
    monkeypatch.setenv("DEPLOY_ENV", "production")
    with pytest.raises(SystemExit):
        s.guard()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("DEPLOY_ENV", "staging")
    with pytest.raises(SystemExit):
        s.guard()


def test_seed_is_idempotent_and_only_adds_missing_people(db, monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "token-de-prueba")
    from app.models import Event, EventAttendee, EventStaffAuthorization, StaffUser, Tenant, User, WebForm
    from scripts import seed_load_staging as s
    first = s.seed(db, 30, 10)
    again = s.seed(db, 30, 10)                                                     # repetir el seed
    assert first == again and again["people"] == 30
    assert db.query(Event).filter_by(event_code=s.EVENT_CODE).count() == 1 and db.query(WebForm).filter_by(slug=s.FORM_SLUG).count() == 1
    assert db.query(User).filter_by(tenant_id=s.TENANT).count() == 30 and db.query(EventAttendee).filter_by(event_id=first["event_id"]).count() == 30
    assert db.query(StaffUser).filter_by(username=s.USERNAME).count() == 1 and db.query(Tenant).filter_by(id=s.TENANT).count() == 1
    assert db.query(EventStaffAuthorization).filter_by(event_id=first["event_id"]).count() == 1
    grown = s.seed(db, 45, 12)                                                     # pedir más personas agrega SOLO las que faltan; el cupo se actualiza
    assert grown["people"] == 45 and grown["capacity"] == 12 and db.query(EventAttendee).filter_by(event_id=first["event_id"]).count() == 45
    assert s.seed(db, 20, 12)["people"] == 45                                      # pedir menos no borra (para eso: purge-data)
    assert s.verify(db)["event_id"] == first["event_id"]                           # verify también imprime el id del evento (respaldo si el log del seed tarda)


@pytest.mark.skipif(any(importlib.util.find_spec(m) is None for m in ("gevent", "locust")), reason="requiere locust/gevent (imagen del generador o entorno local; el CI de la app no los instala)")
def test_locust_outside_the_app_line_is_recorded_end_to_end(tmp_path):
    """Regresión: run_task creaba `Environment` sin `events=locust.events`, los oyentes del locustfile nunca corrían y «[fuera de la app]» no salía en el informe. Aquí un
    servidor de mentira con `Server-Timing` y el generador real (en un subproceso: locust parchea gevent y no debe entrar al proceso de pytest).
    Corre donde locust esté instalado (la imagen del generador o un entorno local); el CI de la aplicación no lo instala y la salta. La comprobación usa `find_spec` (no
    `pytest.importorskip`): importar locust en el proceso de pytest parchea gevent y cuelga la suite.
    """
    import subprocess
    import sys
    driver = tmp_path / "drive.py"
    driver.write_text('''
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import gevent
import locust
from locust.env import Environment
ROOT = sys.argv[1]
sys.path[:0] = [ROOT + "/tests/load", ROOT, ROOT + "/deploy/loadtest"]
seen = {}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        seen["token"] = self.headers.get("X-Timing-Token")
        time.sleep(0.05)
        self.send_response(200); self.send_header("Server-Timing", "app;dur=10.0"); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import run_task, locustfile
env = run_task.make_env(locustfile.FormBurst, "http://127.0.0.1:%d" % srv.server_port)
runner = env.create_local_runner(); runner.start(2, spawn_rate=2)
gevent.sleep(3); runner.quit()
print("ENTRIES", json.dumps(sorted(n for n, _ in env.stats.entries)))
print("TOKEN", bool(seen.get("token")))
''', encoding="utf8")
    env = {**os.environ, "LOAD_EVENT_ID": "1", "LOAD_FORM_SLUG": "carga", "OPS_TOKEN": "token-de-prueba", "LOAD_SUBMIT_RATIO": "0", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(driver), str(ROOT)], env=env, capture_output=True, text=True, encoding="utf8", timeout=60, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TOKEN True" in r.stdout
    names = json.loads(r.stdout.split("ENTRIES ", 1)[1].splitlines()[0])
    assert "[fuera de la app] GET state" in names and "[fuera de la app] GET pagina del formulario" in names, names


def test_report_flags_a_saturated_generator(tmp_path, capsys):
    """El informe muestra CPU y retraso del bucle de cada tarea y avisa cuando el generador no daba abasto (su latencia no es la del servidor)."""
    from scripts import loadgen_report
    entry = {"name": "GET state", "method": "GET", "requests": 10, "failures": 0, "max_ms": 50, "total_ms": 100, "histogram": {"10": 10}}
    lines = [{"scenario": "forms", "task": i, "tasks": 2, "users": 5, "seconds": 10, "entries": [entry], "errors": {}, "generator": g}
             for i, g in enumerate([{"cpu_pct": 40, "lag_p95_ms": 20, "lag_max_ms": 90}, {"cpu_pct": 97, "lag_p95_ms": 900, "lag_max_ms": 4000}])]
    f = tmp_path / "r.txt"
    f.write_text("\n".join("LOADGEN_RESULT " + json.dumps(x) for x in lines), encoding="utf8")
    loadgen_report.main([str(f)])
    out = capsys.readouterr().out
    assert "tarea 0: CPU 40 %" in out and "tarea 1: CPU 97 %" in out
    assert out.count("SATURADO") == 1 and "tarea 1: CPU 97 %, retraso del bucle p95 900 ms, máx 4000 ms  ⚠ SATURADO" in out
