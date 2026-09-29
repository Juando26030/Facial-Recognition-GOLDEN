"""Observabilidad (docs/observabilidad.md): logs JSON sin datos personales, X-Request-ID, manejador global de errores, /healthz, /readyz,
/api/ops/status, /api/ops/deploy-allowed y la pantalla «Estado del sistema»."""
import json
import logging
from datetime import date, datetime, timedelta
from app.timeutil import utcnow

import pytest

from app import obs, ops
from app.models import Event, FormPayment, Job, SystemEvent, WebForm
from tests.conftest import login


# ------------------------------- enmascarado de datos personales -------------------------------
@pytest.mark.parametrize("raw, forbidden", [
    ("registró a 1016100329 con ana.perez@example.com", ["1016100329", "ana.perez@example.com"]),
    ("teléfono +57 317 427 6073 confirmado", ["317 427 6073"]),
    ("token=" + "A" * 40, ["A" * 40]),
    ("encoding [" + ", ".join(["0.1234"] * 128) + "]", ["0.1234"]),
])
def test_mask_pii_hides_ids_emails_phones_tokens_and_encodings(raw, forbidden):
    masked = obs.mask_pii(raw)
    for secret in forbidden:
        assert secret not in masked
    assert masked != raw


def test_mask_pii_keeps_harmless_numbers_readable():
    assert obs.mask_pii("HTTP/1.1 302 Found en 0.184s el 2026-09-26") == "HTTP/1.1 302 Found en 0.184s el 2026-09-26"


def test_mask_url_hides_tokens_ids_and_sensitive_query_values():
    assert obs.mask_url("/b/AbC123tokenSecreto/photo") == "/b/[token]/photo"
    assert obs.mask_url("/c/tok") == "/c/[token]"
    assert obs.mask_url("/api/users/1016100329/cedula") == "/api/users/***/cedula"
    assert obs.mask_url("/f/1/feria/state?k=clave&t=abc&i=inv&x=1") == "/f/1/feria/state?k=[x]&t=[x]&i=[x]&x=1"
    assert obs.mask_ip("203.0.113.77") == "203.0.113.*"


def test_json_formatter_uses_cloud_logging_fields_and_masks_the_traceback():
    rec = logging.LogRecord("golden.test", logging.ERROR, __file__, 1, "falló para %s", ("ana@example.com",), None)
    try:
        raise ValueError("cédula 1016100329 inválida")
    except ValueError:
        import sys
        rec.exc_info = sys.exc_info()
    rec.http_request = {"requestMethod": "GET", "status": 500}
    line = obs.JsonFormatter().format(rec)
    data = json.loads(line)                                                     # una sola línea JSON válida
    assert data["severity"] == "ERROR" and data["httpRequest"]["status"] == 500 and "request_id" in data and data["time"].endswith("+00:00")
    assert "ana@example.com" not in line and "1016100329" not in line
    assert "ValueError" in data["stack_trace"]


def test_trace_header_becomes_the_cloud_logging_trace_field(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "mi-proyecto")
    assert obs._trace_from("105445aa7843bc8bf206b12000100000/1;o=1") == "projects/mi-proyecto/traces/105445aa7843bc8bf206b12000100000"
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    assert obs._trace_from("abc/1") is None


# ------------------------------- X-Request-ID y manejo de errores -------------------------------
def test_request_id_is_generated_or_respected_and_returned(client):
    generated = client.get("/healthz").headers["x-request-id"]
    assert len(generated) == 16
    assert client.get("/healthz", headers={"X-Request-ID": "mi-id-123456"}).headers["x-request-id"] == "mi-id-123456"
    assert client.get("/healthz", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"      # un id raro no se refleja


def test_unhandled_error_gives_a_friendly_message_with_the_id_and_logs_the_trace_masked(client, caplog):
    from app.main import app

    @app.get("/__boom")
    def boom():
        raise RuntimeError("falló con la cédula 1016100329 y ana@example.com")

    from fastapi.testclient import TestClient
    with caplog.at_level(logging.ERROR):
        r = TestClient(app, raise_server_exceptions=False).get("/__boom", headers={"Accept": "application/json", "X-Request-ID": "req-abc-123456"})
    assert r.status_code == 500 and r.json()["request_id"] == "req-abc-123456" and "Ocurrió un error inesperado" in r.json()["detail"]
    assert "RuntimeError" not in r.text and "1016100329" not in r.text                                       # al usuario no le llega la traza
    html = TestClient(app, raise_server_exceptions=False).get("/__boom", headers={"Accept": "text/html"})
    assert html.status_code == 500 and "Algo salió mal" in html.text and "código" in html.text
    line = next(rec for rec in caplog.records if rec.name == "golden.app" and rec.exc_info)
    formatted = obs.JsonFormatter().format(line)
    assert "RuntimeError" in formatted and "1016100329" not in formatted and "ana@example.com" not in formatted   # la traza sí queda en el log, enmascarada


def test_database_down_answers_503_with_retry_after(client):
    from sqlalchemy.exc import OperationalError

    from app.main import app

    @app.get("/__dbdown")
    def dbdown():
        raise OperationalError("SELECT 1", {}, Exception("conexión perdida"))

    from fastapi.testclient import TestClient
    r = TestClient(app, raise_server_exceptions=False).get("/__dbdown", headers={"Accept": "application/json"})
    assert r.status_code == 503 and r.headers["retry-after"] == "3" and "request_id" in r.json()


def test_5xx_are_recorded_for_the_status_screen_with_a_throttle(db):
    ops._last_5xx_write = 0.0
    ops.record_5xx("rid-1", "GET", "/api/x", 500)
    ops.record_5xx("rid-2", "GET", "/api/x", 500)                              # dentro del mismo segundo: se suma, no se escribe
    assert db.query(SystemEvent).filter_by(kind="error_5xx").count() == 1
    ops._last_5xx_write = 0.0
    ops.record_5xx("rid-3", "GET", "/api/x", 502)
    rows = db.query(SystemEvent).filter_by(kind="error_5xx").order_by(SystemEvent.id).all()
    assert len(rows) == 2 and "+1 más" in rows[1].detail


# ------------------------------- /healthz y /readyz -------------------------------
def test_healthz_does_not_touch_any_dependency(client, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("healthz no debe usar la base")

    monkeypatch.setattr(ops, "ping_database", explode)
    monkeypatch.setattr("app.database.SessionLocal", explode)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_ok_lists_each_component(client):
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert set(r.json()["checks"]) == {"database", "storage", "biometrics_model"}                 # en modo «all» también se comprueba el modelo
    assert r.json()["checks"]["database"]["ok"] and "latency_ms" in r.json()["checks"]["database"]


def test_readyz_says_which_component_fails_and_why(client, monkeypatch):
    def down(timeout=2):
        raise TimeoutError("la base no respondió en 2 s")

    monkeypatch.setattr(ops, "ping_database", down)
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    assert "la base no respondió" in r.json()["failing"]["database"] and r.json()["checks"]["storage"]["ok"]
    monkeypatch.undo()

    monkeypatch.setattr("app.ops.get_storage", lambda: type("S", (), {"ping": lambda self: (_ for _ in ()).throw(OSError("disco lleno"))})())
    r = client.get("/readyz")
    assert r.status_code == 503 and "disco lleno" in r.json()["failing"]["storage"]
    monkeypatch.undo()

    monkeypatch.setattr(ops, "model_ready", lambda: (_ for _ in ()).throw(ImportError("falta el modelo")))
    r = client.get("/readyz")
    assert r.status_code == 503 and "falta el modelo" in r.json()["failing"]["biometrics_model"]


def test_readyz_only_checks_the_model_where_biometrics_runs(client, monkeypatch):
    monkeypatch.setattr("app.appmode.MODE", "publico")
    assert "biometrics_model" not in client.get("/readyz").json()["checks"]


def test_database_ping_times_out_instead_of_hanging(monkeypatch):
    import time
    monkeypatch.setattr(ops, "_db_probe", lambda: time.sleep(1))
    with pytest.raises(TimeoutError, match="no respondió"):
        ops.ping_database(timeout=0.1)


# ------------------------------- estado del sistema -------------------------------
def test_status_endpoint_is_admin_only_and_structured(client, factory):
    factory.staff("coordinador", "coord1")
    factory.staff("admin", "root")
    login(client, "coord1")
    assert client.get("/api/ops/status").status_code == 403
    assert client.get("/sistema", follow_redirects=False).status_code == 302
    client.post("/logout")
    login(client, "root")
    r = client.get("/api/ops/status")
    assert r.status_code == 200
    body = r.json()
    ids = [i["id"] for i in body["items"]]
    assert ids == ["version", "database", "connections", "queue", "backup", "client_ip", "bulk_jobs", "events", "emails", "payments", "errors"]
    assert body["level"] in ("green", "yellow", "red") and all(i["level"] in ("green", "yellow", "red") and "reason" in i and "action" in i for i in body["items"])
    page = client.get("/sistema")
    assert page.status_code == 200 and "Estado del sistema" in page.text


def test_status_turns_red_with_the_reason_and_what_to_do(client, factory, db, monkeypatch):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    login(client, "root")
    for _ in range(12):
        db.add(Job(kind="email", payload_json="{}", status="failed", run_at=utcnow(), created_at=utcnow()))       # 12 fallidos
    db.add(Job(kind="x", payload_json="{}", status="queued", run_at=utcnow() - timedelta(minutes=20), created_at=utcnow()))   # esperando hace 20 min
    for _ in range(11):
        db.add(SystemEvent(kind="error_5xx", ref="r", at=utcnow()))
    form = WebForm(event_id=ev.id, name="F", slug="f", manual_status="activo", design_json="{}", test_key="k")
    db.add(form)
    db.commit()
    for i in range(6):                                                                                   # pagos sin conciliar hace más de 15 min
        db.add(FormPayment(form_id=form.id, event_id=ev.id, amount_cents=1, reference=f"R{i}", status="pending", is_test=False, created_at=utcnow() - timedelta(hours=1)))
    db.commit()
    body = client.get("/api/ops/status").json()
    by = {i["id"]: i for i in body["items"]}
    assert body["level"] == "red"
    assert by["queue"]["level"] == "red" and "10 minutos" in by["queue"]["reason"] and by["queue"]["action"]
    assert by["emails"]["level"] == "red" and by["errors"]["level"] == "red" and by["payments"]["level"] == "red"
    assert by["events"]["level"] == "yellow" and "1 evento(s) en curso" in by["events"]["value"]
    assert "reconcile_payments" in by["payments"]["action"]


def test_backup_check_uses_the_newest_file_and_its_age(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    assert ops.check_backup()["level"] == "red"                                                          # carpeta vacía
    f = tmp_path / "golden_db_20260926.sql.gz"
    f.write_bytes(b"x")
    assert ops.check_backup()["level"] == "green"
    old = datetime.now().timestamp() - 60 * 3600
    import os
    os.utime(f, (old, old))
    assert ops.check_backup()["level"] == "red"
    monkeypatch.delenv("BACKUP_DIR")
    assert ops.check_backup()["level"] == "yellow" and "no configurado" in ops.check_backup()["value"]


def test_version_comes_from_env_or_build_info_file(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_COMMIT", raising=False)
    monkeypatch.setenv("BUILD_INFO_FILE", str(tmp_path / "nada"))
    assert ops.check_version()["level"] == "yellow"
    (tmp_path / "info.json").write_text('{"commit": "abcdef1234567890", "date": "2026-09-26T10:00:00Z"}')
    monkeypatch.setenv("BUILD_INFO_FILE", str(tmp_path / "info.json"))
    assert ops.build_info() == {"commit": "abcdef123456", "date": "2026-09-26T10:00:00Z"}
    monkeypatch.setenv("APP_COMMIT", "deadbeefcafe1234")
    monkeypatch.setenv("APP_BUILD_DATE", "hoy")
    assert ops.check_version()["value"] == "deadbeefcafe · hoy" and ops.check_version()["level"] == "green"


# ------------------------------- ¿se puede desplegar? -------------------------------
def test_deploy_is_not_allowed_with_an_event_running_or_about_to_open(client, factory, db, monkeypatch):
    factory.staff("admin", "root")
    login(client, "root")
    assert client.get("/api/ops/deploy-allowed").json() == {"allowed": True, "hours": 3, "reasons": []}
    running = factory.event("en_proceso")
    r = client.get("/api/ops/deploy-allowed").json()
    assert r["allowed"] is False and running.event_code in r["reasons"][0]
    db.query(Event).delete()
    db.commit()

    soon = utcnow() + timedelta(hours=1)                                                        # abre en ~1 h (hora local = UTC-5)
    local = soon - timedelta(hours=5)
    factory.event("creado", start_date=local.date(), event_time_start=local.strftime("%H:%M"))
    r = client.get("/api/ops/deploy-allowed").json()
    assert r["allowed"] is False and "abre en menos de 3 h" in r["reasons"][0]
    assert client.get("/api/ops/deploy-allowed?hours=0").json()["allowed"] is True                       # con N=0 solo importan los eventos en curso
    db.query(Event).delete()
    db.commit()
    factory.event("creado", start_date=date.today() + timedelta(days=5), event_time_start="08:00")
    assert client.get("/api/ops/deploy-allowed").json()["allowed"] is True
    assert client.get("/api/ops/deploy-allowed?hours=999").status_code == 400


def test_deploy_allowed_accepts_the_ops_token_without_a_session(client, factory, monkeypatch):
    factory.event("en_proceso")
    assert client.get("/api/ops/deploy-allowed").status_code == 401
    monkeypatch.setenv("OPS_TOKEN", "token-de-operaciones")
    assert client.get("/api/ops/deploy-allowed", headers={"X-Ops-Token": "malo"}).status_code == 401
    r = client.get("/api/ops/deploy-allowed", headers={"X-Ops-Token": "token-de-operaciones"})
    assert r.status_code == 200 and r.json()["allowed"] is False


def test_cloud_run_health_routes_do_not_end_in_z(client):
    """Cloud Run reserva rutas que terminan en «z» (/healthz da 404 del propio Google): las sondas usan /health y /ready, iguales a las viejas."""
    from app import appmode
    assert client.get("/health").json() == client.get("/healthz").json() == {"status": "ok"}
    ready, readyz = client.get("/ready"), client.get("/readyz")
    assert ready.status_code == readyz.status_code and ready.json()["status"] == readyz.json()["status"]
    for mode in ("publico", "web", "biometria"):
        assert appmode.route_allowed("/health", mode=mode) and appmode.route_allowed("/ready", mode=mode)


def test_static_urls_are_paths_not_absolute_urls(client):
    """Detrás de Firebase la app ve «http» y el host interno de Cloud Run: una URL absoluta quedaba http://…run.app/static/… y el navegador
    la bloqueaba en la página https (sin estilos). Deben salir como ruta, con su ?v=."""
    import re
    html = client.get("/login", headers={"host": "golden-web-staging-abc-ue.a.run.app"}).text
    assets = re.findall(r'(?:href|src)="([^"]*/static/[^"]*)"', html)
    assert assets and all(a.startswith("/static/") and "?v=" in a for a in assets), assets
