"""Fase 3 (E4): comparar secretos nunca lanza aunque quien los manda use caracteres no ASCII."""
import pytest

from app.safeeq import safe_eq


@pytest.mark.parametrize("a,b,expected", [
    ("abc", "abc", True), ("abc", "abd", False), ("", "", True), ("é", "é", True), ("é", "e", False),
    ("token", "tokén", False), (None, "x", False), ("x", None, False), (b"ab", "ab", True), ("\ud800", "x", False),
])
def test_safe_eq(a, b, expected):
    assert safe_eq(a, b) is expected


def test_ops_token_with_non_ascii_header_is_refused_not_a_500(client, monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "t0k3n")
    for value in ("é", "Ã©ñ", "t0k3né"):
        r = client.get("/api/ops/deploy-allowed", headers={"X-Ops-Token": value.encode("utf-8")})
        assert r.status_code in (401, 403), (value, r.status_code)
    assert client.get("/api/ops/deploy-allowed", headers={"X-Ops-Token": "t0k3n"}).status_code not in (401, 403, 500)


def test_wompi_verify_event_with_non_ascii_checksum(monkeypatch):
    from app import wompi
    monkeypatch.setattr(wompi, "config", lambda sandbox: {"events_secret": "s3cret"} if not sandbox else None)
    event = {"data": {"transaction": {"id": "1"}}, "timestamp": 1, "signature": {"properties": [], "checksum": "é" * 64}}
    assert wompi.verify_event(event) is False
    good = dict(event, signature={"properties": [], "checksum": wompi.event_checksum(event, "s3cret")})
    assert wompi.verify_event(good) is True
