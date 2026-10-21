"""IP real del cliente detrás de Firebase Hosting / Cloud Run (docs/15, D2.2 opción D): se quitan del FINAL de X-Forwarded-For las IPs de infraestructura de Google.
Cadenas reales medidas en staging (IP de la terminal: 34.139.233.0, de Cloud Shell = cliente de Google Cloud):
  Firebase (web.app)   [IP real, IP de Google]         p. ej. ["34.139.233.0", "66.102.8.224"] o ["34.139.233.0", "74.125.210.70"]
  run.app directo      [lo que escriba el cliente, IP real]   p. ej. ["1.2.3.4", "34.139.233.0"]"""
import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import ops, security
from app.routers import forms_public

REAL = "34.139.233.0"


def req(xff: str = "", ua: str = "Mozilla", lang: str = "es") -> Request:
    headers = [(b"user-agent", ua.encode()), (b"accept-language", lang.encode())]
    if xff:
        headers.append((b"x-forwarded-for", xff.encode()))
    return Request({"type": "http", "headers": headers, "client": ("169.254.1.1", 1234), "method": "GET", "path": "/"})


@pytest.fixture(autouse=True)
def strip_mode(monkeypatch):
    monkeypatch.setenv("XFF_STRIP_GOOGLE", "1")
    monkeypatch.setenv("TRUST_CF_CONNECTING_IP", "0")
    monkeypatch.delenv("XFF_STRIP_CIDRS", raising=False)
    security.reload_infra()
    security._events.clear()
    security._google_hits.clear()
    yield
    security.reload_infra()


# ------------------------------------------------------------------ la lista de rangos
def test_snapshot_contains_the_observed_google_proxies_and_not_cloud_customers():
    for proxy in ("66.102.8.224", "74.125.210.70"):            # las dos IPs de Google vistas por Firebase Hosting en staging
        assert security.is_google_infra(proxy), proxy
    assert not security.is_google_infra(REAL)                  # Cloud Shell: cliente de Google Cloud (cloud.json) = visitante normal
    assert not security.is_google_infra("1.2.3.4") and not security.is_google_infra("no-es-ip")


def test_subtract_removes_customer_ranges_from_google_ones():
    spec = importlib.util.spec_from_file_location("refresh_google_cidrs", "scripts/refresh_google_cidrs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import ipaddress as ip
    goog = {"prefixes": [{"ipv4Prefix": "8.8.0.0/16"}, {"ipv6Prefix": "2001:4860::/32"}], "creationTime": "2026-09-29T00:00:00"}
    cloud = {"prefixes": [{"ipv4Prefix": "8.8.8.0/24"}, {"ipv4Prefix": "34.0.0.0/8"}], "creationTime": "2026-09-29T00:00:00"}
    header, result = mod.build(goog, cloud)
    assert any(line.startswith("# generated: 2026-09-29") for line in header)
    assert not any(ip.ip_address("8.8.8.8") in n for n in result if n.version == 4)      # el trozo de clientes se fue
    assert any(ip.ip_address("8.8.4.4") in n for n in result if n.version == 4) and any(ip.ip_address("8.8.9.1") in n for n in result if n.version == 4)
    assert any(n.version == 6 for n in result)


# ------------------------------------------------------------------ los dos caminos
def test_firebase_path_picks_the_real_ip_and_ignores_the_google_hop():
    for google in ("66.102.8.224", "74.125.210.70"):           # la segunda entrada cambia entre llamadas
        assert security.client_ip(req(f"{REAL}, {google}")) == REAL
        assert security.limit_ip(req(f"{REAL}, {google}")) == REAL


def test_run_app_direct_path_cannot_fake_the_ip():
    assert security.client_ip(req(f"1.2.3.4, {REAL}")) == REAL                                       # la cabecera falsa queda a la izquierda
    assert {security.limit_ip(req(f"{fake}, {REAL}")) for fake in (f"9.9.{i}.{i}" for i in range(50))} == {REAL}     # rotar la falsa no da un cubo nuevo
    assert security.client_ip(req(f"66.102.8.1, 74.125.1.1, 1.2.3.4, {REAL}")) == REAL             # ni anteponer IPs de Google


def test_a_visitor_on_the_vm_style_setup_is_unchanged_when_strip_is_off(monkeypatch):
    monkeypatch.setenv("XFF_STRIP_GOOGLE", "0")
    monkeypatch.setenv("XFF_CLIENT_INDEX", "0")
    assert security.client_ip(req(f"{REAL}, 66.102.8.224")) == REAL and security.client_ip(req("")) == "169.254.1.1"


# ------------------------------------------------------------------ llamadas internas (Cloud Tasks, Scheduler, Jobs)
def test_internal_calls_have_only_google_hops_and_are_not_affected(client):
    chain = "74.125.210.70"
    assert security.client_ip(req(chain)) == chain and security.limit_ip(req(chain)) is None      # nada que limitar por IP
    r = client.post("/internal/jobs/run", headers={"X-Forwarded-For": chain})
    assert r.status_code in (401, 403)                                                            # sigue mandando el token OIDC, no la IP
    assert client.get("/health", headers={"X-Forwarded-For": chain}).status_code == 200


def test_all_google_chain_does_not_block_everyone_at_once(client, monkeypatch):
    chain = {"X-Forwarded-For": "74.125.210.70"}
    for i in range(25):                                        # 25 usuarios distintos fallando desde «la misma IP de Google» (> el tope de 20 por IP)
        assert client.post("/login", data={"username": f"nadie{i}", "password": "x"}, headers=chain).status_code == 401
    forms_public._limiter.reset()
    form = SimpleNamespace(id=7)
    for _ in range(500):
        forms_public._limit(None, req("74.125.210.70"), "view", form, 5)                          # sin 429: no hay límite por IP para IPs de Google
    forms_public._limiter.reset()
    with pytest.raises(HTTPException) as exc:                                                      # con una IP real, el límite sí funciona
        for _ in range(50):
            forms_public._limit(None, req(f"{REAL}, 66.102.8.224"), "view", form, 5)
    assert exc.value.status_code == 429
    assert security.ip_health()["google_ip_hits"] >= 100          # (el contador guarda como mucho los últimos 200 instantes)


def test_real_ip_limit_still_blocks_from_a_direct_path_attacker(client):
    chain = lambda i: {"X-Forwarded-For": f"8.{i}.8.8, {REAL}"}      # noqa: E731 — cada intento con una IP falsa distinta
    codes = [client.post("/login", data={"username": f"u{i}", "password": "x"}, headers=chain(i)).status_code for i in range(22)]
    assert codes[:20] == [401] * 20 and codes[20] == 429             # el tope de 20 por IP real se alcanza aunque rote la cabecera falsa


# ------------------------------------------------------------------ lista vieja: avisos de «Estado del sistema»
def test_stale_range_list_is_detected_as_a_concentrated_ip(monkeypatch):
    monkeypatch.setenv("XFF_STRIP_CIDRS", "66.102.0.0/20")                              # lista vieja: le falta 74.125.x
    security.reload_infra()
    for i in range(150):                                                                # 150 visitantes distintos que Firebase entrega con un proxy nuevo al final
        security.limit_ip(req(f"203.0.113.{i % 250}, 74.125.210.70", ua=f"Navegador-{i % 40}"))
    h = security.ip_health()
    assert h["concentrated"] and h["top_share"] >= 0.99 and h["distinct_clients"] >= 20
    item = ops.check_client_ip()
    assert item["level"] == "yellow" and "navegadores" in item["value"] and "refresh_google_cidrs" in item["action"]


def test_status_is_red_when_whole_chains_are_google_and_green_with_a_fresh_list():
    for _ in range(3):
        security.limit_ip(req("74.125.210.70"))
    assert ops.check_client_ip()["level"] == "red"
    security._google_hits.clear()
    security._events.clear()
    item = ops.check_client_ip()
    assert item["level"] in ("green", "yellow")                                       # green si el archivo tiene < 45 días; yellow si ya venció (a propósito)
    assert item["data"]["list_networks"] > 50


def test_status_warns_when_the_list_has_no_date_or_is_old(monkeypatch):
    monkeypatch.setenv("XFF_STRIP_CIDRS", "66.102.0.0/20")
    security.reload_infra()
    assert ops.check_client_ip()["level"] == "yellow"                                  # lista puesta a mano sin fecha
    monkeypatch.setattr(security, "infra_info", lambda: {"networks": 10, "generated": "2020-01-01", "source": "archivo"})
    assert ops.check_client_ip()["level"] == "yellow" and "días" in ops.check_client_ip()["value"]


def test_diagnostic_endpoint_flags_google_hops(client, monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "t")
    r = client.get("/api/ops/client-ip", headers={"X-Ops-Token": "t", "X-Forwarded-For": f"{REAL}, 66.102.8.224"}).json()
    assert r["google_infra"] == [False, True] and r["chosen_ip"] == REAL and r["strip_google"] is True and r["ranges"]["networks"] > 50
