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


_RETRY_DRIVER = '''
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import gevent
import locust
ROOT, MODE = sys.argv[1], sys.argv[2]
sys.path[:0] = [ROOT + "/tests/load", ROOT, ROOT + "/deploy/loadtest"]
hits = {"state": 0, "submit": 0}
class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", headers=()):
        raw = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(raw)))
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path.endswith("/state"):
            hits["state"] += 1
            if hits["state"] == 1:
                return self._send(429, "Rate exceeded.", "text/plain; charset=utf-8")       # el 429 de Cloud Run: texto plano
        self._send(200, "{}")
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        hits["submit"] += 1
        if MODE == "giveup" or hits["submit"] <= 3:
            return self._send(503, json.dumps({"busy": True}), headers=[("Retry-After", "0")])
        self._send(200, json.dumps({"ok": True}))
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import run_task, locustfile
env = run_task.make_env(locustfile.FormBurst, "http://127.0.0.1:%d" % srv.server_port)
runner = env.create_local_runner(); runner.start(1, spawn_rate=1)
t0 = time.time()
while locustfile.DONE["users"] < 1 and time.time() - t0 < 30: gevent.sleep(0.2)
runner.quit()
print("STATS", json.dumps({n: [e.num_requests, e.num_failures] for (n, _), e in env.stats.entries.items()}))
'''


@pytest.mark.skipif(any(importlib.util.find_spec(m) is None for m in ("gevent", "locust")), reason="requiere locust/gevent (imagen del generador o entorno local; el CI de la app no los instala)")
@pytest.mark.parametrize("mode", ["retries", "giveup"])
def test_generator_retries_like_the_browser_and_reports_the_final_result_per_user(tmp_path, mode):
    """Mismas reglas que el navegador: 503 «busy» y el 429 de infraestructura se reintentan con la misma sid; son contrapresión (no fallos); al final cada usuario deja «inscrito» o
    «se rindió tras N reintentos» (ese sí es fallo). Corre donde locust esté instalado (subproceso: locust parchea gevent)."""
    import subprocess
    import sys
    driver = tmp_path / "drive_retry.py"
    driver.write_text(_RETRY_DRIVER, encoding="utf8")
    env = {**os.environ, "LOAD_EVENT_ID": "1", "LOAD_FORM_SLUG": "carga", "OPS_TOKEN": "token-de-prueba", "LOAD_SUBMIT_RATIO": "1", "LOAD_THINK_MAX": "1", "PYTHONIOENCODING": "utf-8",
           "LOAD_RETRY_BASE_MS": "20", "LOAD_RETRY_DEADLINE": "1.5" if mode == "giveup" else "30"}
    r = subprocess.run([sys.executable, str(driver), str(ROOT), mode], env=env, capture_output=True, text=True, encoding="utf8", timeout=90, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    stats = json.loads(r.stdout.split("STATS ", 1)[1].splitlines()[0])
    assert stats["GET state (contrapresión 429)"][0] == 1 and stats["GET state (contrapresión 429)"][1] == 0          # el 429 de Cloud Run se reintenta y no es fallo
    assert stats["GET state"] == [1, 0]
    real_failures = {n: v[1] for n, v in stats.items() if v[1] and not n.startswith("[usuario]")}
    assert real_failures == {}                                                                                        # ni un solo intento «ocupado» cuenta como fallo
    if mode == "retries":
        assert stats["POST envio (contrapresión 503)"] == [1, 0] and stats["POST envio (reintento por contrapresión) (contrapresión 503)"] == [2, 0]
        assert stats["POST envio (reintento por contrapresión)"] == [1, 0]
        assert stats["[usuario] inscrito"] == [1, 0]
    else:
        gave_up = [n for n in stats if n.startswith("[usuario] se rindió tras ")]
        assert len(gave_up) == 1 and stats[gave_up[0]] == [1, 1]                                                       # rendirse SÍ es un fallo del usuario
        assert "[usuario] inscrito" not in stats


def test_report_separates_backpressure_and_shows_the_final_result_per_user(tmp_path, capsys):
    from scripts import loadgen_report

    def entry(name, n, fails=0, ms=100):
        return {"name": name, "method": "POST", "requests": n, "failures": fails, "max_ms": ms * 3, "total_ms": ms * n, "histogram": {str(ms): n}}

    rows = [entry("POST envio", 40, ms=50), entry("POST envio (contrapresión 503)", 60, ms=20), entry("GET state (contrapresión 429)", 5, ms=20), entry("GET state", 100, ms=30),
            entry("[usuario] inscrito", 90, ms=4000), entry("[usuario] cupo lleno", 6, ms=9000), entry("[usuario] se rindió tras 12 reintentos", 4, fails=4, ms=150000)]
    f = tmp_path / "r.txt"
    f.write_text("LOADGEN_RESULT " + json.dumps({"scenario": "forms", "task": 0, "tasks": 1, "users": 100, "seconds": 60, "entries": rows, "errors": {}}), encoding="utf8")
    loadgen_report.main([str(f)])
    out = capsys.readouterr().out
    main_table = out.split("Contrapresión")[0]
    assert "| POST envio |" in main_table and "contrapresión" not in main_table and "[usuario]" not in main_table                # no ensucian la tabla principal
    assert "| POST envio (contrapresión 503) | 60 | 60 %" in out and "| GET state (contrapresión 429) | 5 | 5 %" in out
    assert "Resultado FINAL por usuario virtual que envía (100 usuarios" in out
    assert "| inscrito | 90 | 90.0 |" in out and "| cupo lleno | 6 | 6.0 |" in out and "| se rindió tras 12 reintentos | 4 | 4.0 |" in out


def _forms_report(tmp_path, capsys, rows, gens=None, verify=None):
    from scripts import loadgen_report
    f = tmp_path / "r.txt"
    lines = ["LOADGEN_RESULT " + json.dumps({"scenario": "forms", "task": 0, "tasks": 1, "users": 100, "seconds": 60, "entries": rows, "errors": {}, "generator": gens or {"cpu_pct": 40, "lag_p95_ms": 20, "lag_max_ms": 90}})]
    if verify:
        lines.append("LOAD_VERIFY " + json.dumps(verify))
    f.write_text("\n".join(lines), encoding="utf8")
    code = loadgen_report.main([str(f)])
    return code, capsys.readouterr().out


def _e(name, n, ms, fails=0):
    return {"name": name, "method": "GET", "requests": n, "failures": fails, "max_ms": ms * 2, "total_ms": ms * n, "histogram": {str(ms): n}}


def test_forms_criterion_passes_with_the_agreed_thresholds(tmp_path, capsys):
    rows = [_e("GET state", 100, 300), _e("[usuario] inscrito", 90, 40000), _e("[usuario] cupo lleno", 10, 20000), _e("POST envio (contrapresión 503)", 500, 20)]
    code, out = _forms_report(tmp_path, capsys, rows, verify={"confirmed_submissions": 90, "capacity": 90, "oversold": 0, "duplicate_persons": 0, "duplicate_sids": 0})
    assert code == 0 and "Criterio forms → CUMPLE" in out
    assert "min(capacidad 90, usuarios únicos que envían 100) = 90" in out and "meta 60 s: alcanzada" in out


@pytest.mark.parametrize("rows,gens,verify,needle", [
    ([_e("GET state", 100, 2500), _e("[usuario] inscrito", 100, 1000)], None, None, "✘ state p95"),                                                    # state lento
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 100, 130000)], None, None, "✘ p95 del tiempo total de quien se inscribe"),                   # tiempo total > 120 s
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 95, 1000), _e("[usuario] se rindió tras 9 reintentos", 5, 150000, 5)], None, None, "✘ 95.0 %"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 98, 1000), _e("[usuario] no terminó (cortado al agotarse LOAD_DURATION)", 2, 360000, 2)], None, None, "✘ 98.0 %"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 100, 1000), _e("POST envio (contrapresión 502)", 3, 20)], None, None, "✘ 3 respuestas 5xx distintas"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 100, 1000), _e("POST envio (contrapresión 503 infra)", 1, 20)], None, None, "✘ 1 respuestas 5xx distintas"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 100, 1000)], {"cpu_pct": 95, "lag_p95_ms": 20, "lag_max_ms": 90}, None, "✘ generadores saturados"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 90, 1000), _e("[usuario] cupo lleno", 10, 1000)], None, {"confirmed_submissions": 91, "capacity": 90, "oversold": 1, "duplicate_persons": 0, "duplicate_sids": 0}, "✘ base: sobreventas 1"),
    ([_e("GET state", 100, 300), _e("[usuario] inscrito", 90, 1000), _e("[usuario] cupo lleno", 10, 1000)], None, {"confirmed_submissions": 80, "capacity": 90, "oversold": 0, "duplicate_persons": 0, "duplicate_sids": 0}, "✘ base: inscripciones confirmadas 80"),
])
def test_forms_criterion_fails_when_any_agreed_threshold_is_missed(tmp_path, capsys, rows, gens, verify, needle):
    code, out = _forms_report(tmp_path, capsys, rows, gens=gens, verify=verify)
    assert code == 1 and "Criterio forms → NO CUMPLE" in out and needle in out, out


def test_forms_criterion_asks_for_the_database_check_when_missing(tmp_path, capsys):
    code, out = _forms_report(tmp_path, capsys, [_e("GET state", 100, 300), _e("[usuario] inscrito", 100, 1000)])
    assert code == 0 and "falta la línea LOAD_VERIFY" in out and "a falta de la verificación de la base" in out
