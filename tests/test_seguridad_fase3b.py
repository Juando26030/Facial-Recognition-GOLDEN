"""Cierre de seguridad, Fase 3 (lote b, nov-2026): alcance débil.
(a) /colors no se pisa; (b) notas del calendario y solicitudes de privacidad por cliente; (c) matriz de roles con ENFORCE_STAFF_TENANT=1;
(d) simulacro de caída solo en staging; (e) sondeo del ingreso de digitadores con tope; (f) CSP; (g) SRI.
Las de «fuente» no usan base; las demás usan el Postgres de pruebas."""
import re
from pathlib import Path

import pytest

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------ de fuente (corren sin base)
def test_a_colors_overwrite_is_admin_only_in_source():
    body = _src("app/routers/events.py")
    start = body.index("def save_color(")
    chunk = body[start:body.index("def _color_or_404")]
    assert "status_code=409" in chunk and '("admin", "super_admin")' in chunk
    assert chunk.index("status_code=409") < chunk.index("color.hex = hex_value.lower()")


def test_b_calendar_and_privacy_requests_use_the_tenant_scope():
    cal = _src("app/routers/calendar.py")
    assert "staff_tenant_enforced" in cal and "assert_same_tenant" in cal
    assert "_note_tenant(n) == staff.tenant_id" in cal
    pr = _src("app/routers/privacy_requests.py")
    assert pr.count("assert_same_tenant") >= 3 and "staff_tenant_enforced(staff)" in pr
    assert "tenant_id=staff.tenant_id" in pr                      # claim_for no mezcla clientes
    assert pr.count("Depends(ADMIN)") == 5 and 'ADMIN = require_role("admin")' in pr


def test_c_every_direct_event_lookup_in_events_and_transfer_checks_tenant():
    ev = _src("app/routers/events.py")
    for fn in ("update_event", "create_event_staff", "_event_for_admin", "revert_to_created_info", "list_status_changes"):
        if f"def {fn}(" in ev:
            seg = ev[ev.index(f"def {fn}("):]
            seg = seg[:seg.index("\n@router") if "\n@router" in seg else len(seg)]
            assert "assert_event_tenant" in seg, fn
    tr = _src("app/routers/event_transfer.py")
    assert tr.count("assert_event_tenant(event, staff)") == 2


def test_d_simulate_crash_only_staging_with_chaos_and_never_in_deploy_files():
    ops = _src("app/routers/ops.py")
    seg = ops[ops.index("def simulate_crash("):]
    seg = seg[:seg.index("@pages.get")]
    assert 'os.getenv("DEPLOY_ENV", "").strip().lower() != "staging"' in seg and 'os.getenv("CHAOS_ENABLED") != "1"' in seg
    assert "status_code=404" in seg and seg.index("status_code=404") < seg.index("add_task")
    for path in [*(ROOT / "deploy" / "gcp").rglob("*"), *(ROOT / ".github").rglob("*"), ROOT / "Dockerfile", ROOT / "deploy" / "docker-compose.yml"]:
        if path.is_file() and path.suffix in {".yaml", ".yml", ".sh", ".service", ".conf", ".env", ""}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "CHAOS_ENABLED" not in text, f"{path} activa o menciona CHAOS_ENABLED"


def test_d_production_env_files_do_not_set_chaos():
    for path in (ROOT / "deploy").rglob("*.yaml"):
        assert "CHAOS" not in path.read_text(encoding="utf-8", errors="ignore")
    for path in ROOT.glob(".env*"):
        if path.name.endswith("example"):
            assert "CHAOS_ENABLED=1" not in path.read_text(encoding="utf-8", errors="ignore")


def test_e_waiting_endpoints_have_a_poll_limit_and_one_use_token():
    src = _src("app/routers/login_approval.py")
    assert src.count("_throttled(request, req)") == 2 and "status_code=429" in src
    lc = _src("app/login_control.py")
    assert "REQUEST_TTL = timedelta(minutes=5)" in lc and "def consume_approved" in lc and "POLL_MAX_PER_TOKEN" in lc


def test_e_poll_limiter_is_a_sliding_window():
    from app import login_control as lc
    lc.reset_poll_limits()
    assert all(lc.poll_allowed("k", 3, now=100.0 + i) for i in range(3))
    assert not lc.poll_allowed("k", 3, now=103.0)
    assert lc.poll_allowed("otro", 3, now=103.0)                    # otra clave no se afecta
    assert lc.poll_allowed("k", 3, now=100.0 + lc.POLL_WINDOW + 1)  # pasada la ventana vuelve a dejar
    lc.reset_poll_limits()
    # lo normal (una pregunta cada 3 s) queda muy por debajo del tope
    assert lc.POLL_MAX_PER_TOKEN >= 3 * (60 / lc.POLL_SECONDS)


def test_f_csp_today_has_no_script_src_and_no_report_only():
    main = _src("app/main.py")
    assert "Content-Security-Policy-Report-Only" not in main
    assert "object-src 'none'; base-uri 'self'" in main and "script-src" not in main      # el plan para endurecerla está en docs/FASE_3_SEGURIDAD.md
    doc = _src("docs/FASE_3_SEGURIDAD.md")
    assert "script-src" in doc and "Report-Only" in doc


def test_g_leaflet_is_pinned_and_sri_status_documented():
    js = _src("static/js/gw-map.js")
    assert re.search(r"LEAFLET_VERSION = '\d+\.\d+\.\d+'", js)
    if "integrity" not in js:
        assert "SRI de Leaflet" in _src("docs/FASE_3_SEGURIDAD.md")
    for t in ROOT.joinpath("templates").glob("*.html"):
        for m in re.finditer(r"<script[^>]+src=\"https://cdnjs[^>]+>", t.read_text(encoding="utf-8")):
            assert "integrity=" in m.group(0), f"{t.name}: script de CDN sin SRI"


# ------------------------------------------------------------------------------------------------ con base
def test_a_colors_coordinator_cannot_overwrite_but_admin_can(client, factory):
    factory.staff("coordinador", "coo")
    factory.staff("admin", "adm")
    login(client, "coo")
    assert client.post("/api/colors", json={"name": "Rojo Golden", "hex": "#C0392B"}).status_code == 200
    r = client.post("/api/colors", json={"name": "rojo golden", "hex": "#000000"})
    assert r.status_code == 409 and "administrador" in r.json()["detail"]
    assert client.post("/api/colors", json={"name": "Rojo Golden", "hex": "#c0392b"}).status_code == 200      # mismo tono: idempotente
    assert [c["hex"] for c in client.get("/api/colors").json()] == ["#c0392b"]
    client.post("/logout"); client.cookies.clear()
    login(client, "adm")
    r = client.post("/api/colors", json={"name": "Rojo Golden", "hex": "#111111"})
    assert r.status_code == 200 and r.json()["hex"] == "#111111"


def test_b_calendar_notes_isolated_by_client_when_flag_on(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("acme"); factory.tenant("beta")
    factory.staff("coordinador", "ca", tenant_id="acme")
    factory.staff("coordinador", "ca2", tenant_id="acme")
    factory.staff("coordinador", "cb", tenant_id="beta")
    glob = factory.staff("coordinador", "cg")
    params = {"start": "2026-01-01", "end": "2026-12-31"}
    login(client, "cb")
    nid = client.post("/api/calendar/notes", json={"date": "2026-05-05", "text": "nota de beta"}).json()["id"]
    client.post("/logout"); client.cookies.clear()
    login(client, "ca")
    assert client.get("/api/calendar/notes", params=params).json() == []
    assert client.delete(f"/api/calendar/notes/{nid}").status_code == 404
    assert client.post("/api/calendar/notes", json={"date": "2026-05-05", "text": "x", "target_staff_ids": [glob.id]}).status_code == 400
    assert all(p["username"] != "cb" for p in client.get("/api/calendar/notifiable-staff").json())
    own = client.post("/api/calendar/notes", json={"date": "2026-05-06", "text": "nota de acme"}).json()["id"]
    client.post("/logout"); client.cookies.clear()
    login(client, "ca2")
    assert [n["id"] for n in client.get("/api/calendar/notes", params=params).json()] == [own]
    client.post("/logout"); client.cookies.clear()
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "0")
    login(client, "ca")
    assert nid in {n["id"] for n in client.get("/api/calendar/notes", params=params).json()}      # apagado = comportamiento de siempre


def test_b_privacy_requests_isolated_by_client_when_flag_on(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.event(tenant_id="acme")
    ev_b = factory.event(tenant_id="beta")
    factory.staff("admin", "adm_a", tenant_id="acme")
    factory.staff("admin", "adm_b", tenant_id="beta")
    factory.staff("admin", "adm_g")
    body = {"channel": "email", "request_type": "reclamo", "holder_name": "Ana", "cedula": "123"}
    login(client, "adm_b")
    rb = client.post("/api/privacy-requests", json={**body, "event_id": ev_b.id}).json()
    client.post("/logout"); client.cookies.clear()
    login(client, "adm_a")
    assert client.post("/api/privacy-requests", json={**body, "event_id": ev_b.id}).status_code == 404
    mine = client.post("/api/privacy-requests", json=body).json()               # sin evento: queda a nombre de su cliente
    assert [r["id"] for r in client.get("/api/privacy-requests").json()] == [mine["id"]]
    assert client.put(f"/api/privacy-requests/{rb['id']}/status", json={"status": "en_tramite"}).status_code == 404
    assert client.put(f"/api/privacy-requests/{rb['id']}/claim-flag", json={"active": True}).status_code == 404
    client.post("/logout"); client.cookies.clear()
    login(client, "adm_b")
    assert client.put(f"/api/privacy-requests/{rb['id']}/claim-flag", json={"active": True}).status_code == 200
    client.post("/logout"); client.cookies.clear()
    login(client, "adm_a")
    assert client.get("/api/privacy-requests/claim/123").json()["claim_in_progress"] is False       # el reclamo de otro cliente no se ve
    client.post("/logout"); client.cookies.clear()
    login(client, "adm_g")                                                       # personal global: ve todo
    assert len(client.get("/api/privacy-requests").json()) == 2


ROLE_MATRIX = ("coordinador", "comercial", "admin")
EVENT_ENDPOINTS = ("consent-text", "analytics/registro", "areas", "inventory", "badge-template", "biometric-setup", "timing-report")


@pytest.mark.parametrize("role", ROLE_MATRIX)
def test_c_role_matrix_with_enforce_staff_tenant(client, factory, monkeypatch, role):
    """Con el interruptor encendido, el personal con cliente no alcanza NINGÚN endpoint de eventos de otro cliente (404 «Evento no encontrado»); el global y el del mismo cliente sí pasan la puerta."""
    ev_other = factory.event(tenant_id="beta")
    ev_own = factory.event(tenant_id="acme")
    factory.staff(role, "limitado", tenant_id="acme")
    factory.staff(role, "global")

    def not_found(path):
        r = client.get(path)
        return r.status_code == 404 and r.json().get("detail") == "Evento no encontrado"

    def role_denied(ep):
        """La puerta del ROL va antes que la del cliente: si el rol no alcanza ese endpoint (p. ej. timing-report es de admin; zonas excluye al comercial puro) da 403 también en el evento propio, y no se filtra nada."""
        return client.get(f"/api/events/{ev_own.id}/{ep}").status_code == 403

    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    login(client, "limitado")
    for ep in EVENT_ENDPOINTS:
        if role_denied(ep):
            assert client.get(f"/api/events/{ev_other.id}/{ep}").status_code == 403, ep
            continue
        assert not_found(f"/api/events/{ev_other.id}/{ep}"), ep
        assert not not_found(f"/api/events/{ev_own.id}/{ep}"), ep
    assert ev_other.id not in {e["id"] for e in client.get("/api/events").json()}
    client.post("/logout"); client.cookies.clear()
    login(client, "global")
    for ep in EVENT_ENDPOINTS:
        assert not not_found(f"/api/events/{ev_other.id}/{ep}"), ep
    client.post("/logout"); client.cookies.clear()
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "0")
    login(client, "limitado")
    for ep in EVENT_ENDPOINTS:
        assert not not_found(f"/api/events/{ev_other.id}/{ep}"), ep      # apagado: nada cambia


@pytest.mark.parametrize("role", ("digitador", "cliente"))
def test_c_authorized_temp_accounts_are_also_cut_by_tenant(client, factory, monkeypatch, role):
    ev_other = factory.event(tenant_id="beta")
    s = factory.staff(role, "temp", tenant_id="acme")
    factory.authorize(ev_other, s)
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    monkeypatch.setenv("DIGITADOR_LOGIN_CONTROL", "0")
    login(client, "temp")
    r = client.get(f"/api/events/{ev_other.id}/consent-text")
    assert r.status_code == 404 and r.json()["detail"] == "Evento no encontrado"


def test_e_waiting_endpoints_throttle_and_stay_quiet_without_a_request(client, monkeypatch):
    from app import login_control
    monkeypatch.setattr(login_control, "POLL_MAX_PER_IP", 5)
    codes = [client.post("/api/ingreso/estado").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3
    assert client.post("/api/ingreso/estado").json()["status"] == "throttled"
    assert client.post("/api/ingreso/cancelar").status_code == 429                  # comparten el tope por IP
