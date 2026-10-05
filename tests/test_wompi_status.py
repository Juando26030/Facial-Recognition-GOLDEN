"""Estado público de Wompi: `service_status` NUNCA espera a la red (refresco en un hilo, una consulta a la vez), conserva el último resultado bueno si las consultas fallan y el `quote` del
formulario no se frena aunque la página de estado de Wompi tarde."""
import json
import threading
import time
import urllib.error

import pytest

from app import wompi


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _ok(indicator="minor", description="Degraded"):
    return _Resp(json.dumps({"status": {"indicator": indicator, "description": description}}).encode())


@pytest.fixture
def expired(monkeypatch):
    """Caché vacía y vencida (sin datos) y sin refresco en curso."""
    monkeypatch.setitem(wompi._status, "at", 0.0)
    monkeypatch.setitem(wompi._status, "data", None)
    monkeypatch.setitem(wompi._status, "ok_at", 0.0)
    monkeypatch.setattr(wompi, "_refreshing", False)


def _wait_idle(timeout=10):
    deadline = time.time() + timeout
    while wompi._refreshing and time.time() < deadline:
        time.sleep(0.01)
    assert not wompi._refreshing


def _blocked_fetch(monkeypatch, response):
    """urlopen que no responde hasta que se libere `gate`; cuenta las consultas."""
    gate, calls = threading.Event(), []

    def fake(req, timeout=0):
        calls.append(timeout)
        gate.wait(10)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(wompi.urllib.request, "urlopen", fake)
    return gate, calls


def test_service_status_never_waits_for_the_network_and_picks_up_the_result_afterwards(expired, monkeypatch):
    gate, calls = _blocked_fetch(monkeypatch, _ok())
    t0 = time.time()
    first = wompi.service_status()
    assert time.time() - t0 < 0.3 and first == {"indicator": "unknown", "description": ""}      # sin datos: «unknown» al instante (nunca avisa de lo que no consta)
    assert wompi.service_problem() is None and time.time() - t0 < 0.5
    gate.set()
    _wait_idle()
    assert wompi.service_status() == {"indicator": "minor", "description": "Degraded"}          # el refresco terminó: ya hay dato
    assert len(calls) == 1 and calls[0] == wompi.STATUS_TIMEOUT                                 # una sola consulta, con el timeout corto


def test_expired_cache_starts_exactly_one_refresh_however_many_requests_arrive(expired, monkeypatch):
    gate, calls = _blocked_fetch(monkeypatch, _ok("major", "Outage"))
    results = []
    threads = [threading.Thread(target=lambda: results.append(wompi.service_status()["indicator"])) for _ in range(50)]
    [t.start() for t in threads]
    [t.join(5) for t in threads]
    assert len(results) == 50 and set(results) == {"unknown"}                                   # ninguna esperó
    time.sleep(0.2)
    assert len(calls) == 1                                                                      # y solo hubo UNA consulta (antes: una por petición)
    gate.set()
    _wait_idle()
    assert wompi.service_problem()["indicator"] == "major"


def test_a_stale_result_is_served_at_once_while_it_refreshes(expired, monkeypatch):
    now = time.time()
    monkeypatch.setitem(wompi._status, "data", {"indicator": "minor", "description": "Degraded"})
    monkeypatch.setitem(wompi._status, "at", now - 120)
    monkeypatch.setitem(wompi._status, "ok_at", now - 120)                                       # vencido (60 s) pero dentro de los 15 min
    gate, calls = _blocked_fetch(monkeypatch, _ok("none", "All Systems Operational"))
    t0 = time.time()
    assert wompi.service_status()["indicator"] == "minor" and time.time() - t0 < 0.3             # sirve el viejo mientras refresca
    gate.set()
    _wait_idle()
    assert wompi.service_status()["indicator"] == "none" and len(calls) == 1


def test_failures_keep_the_last_good_result_until_the_max_age_and_are_not_retried_every_request(expired, monkeypatch):
    now = time.time()
    good = {"indicator": "minor", "description": "Degraded"}
    monkeypatch.setitem(wompi._status, "data", good)
    monkeypatch.setitem(wompi._status, "at", now - 120)
    monkeypatch.setitem(wompi._status, "ok_at", now - 100)
    calls = []

    def fail(req, timeout=0):
        calls.append(1)
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr(wompi.urllib.request, "urlopen", fail)
    assert wompi.refresh_now() == good                                                           # la consulta falló: se conserva el último bueno
    for _ in range(20):
        assert wompi.service_status() == good                                                    # el intento fallido también cuenta: no se reintenta en cada petición…
    assert len(calls) == 1                                                                       # …hasta que pase STATUS_TTL
    monkeypatch.setitem(wompi._status, "ok_at", now - wompi.STATUS_MAX_STALE - 5)                # el último bueno ya es demasiado viejo
    assert wompi.refresh_now()["indicator"] == "unknown"                                         # entonces «unknown»: no se afirma lo que ya no consta


def test_unintelligible_answers_are_failures_not_problems(expired, monkeypatch):
    for body in (b"esto no es json", b'{"status": {"indicator": "raro"}}', b"{}", b"null"):
        monkeypatch.setattr(wompi.urllib.request, "urlopen", lambda *a, _b=body, **k: _Resp(_b))
        assert wompi.refresh_now()["indicator"] == "unknown" and wompi.service_problem() is None


def test_the_quote_is_not_slowed_by_a_slow_wompi_status_page(client, factory, monkeypatch):
    """El `quote` de un formulario con pago llamaba a la página de estado dentro de la petición (hasta ~8 s con un hilo y una conexión retenidos, y una consulta por petición simultánea)."""
    from tests.test_form_payments import _event, _url, _with_payment
    for k, v in {"WOMPI_PUBLIC_KEY": "pub_prod_x", "WOMPI_INTEGRITY_SECRET": "int_x", "WOMPI_EVENTS_SECRET": "ev_x", "WOMPI_PRIVATE_KEY": "prv_prod_x"}.items():
        monkeypatch.setenv(k, v)
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    monkeypatch.setitem(wompi._status, "at", 0.0)
    monkeypatch.setitem(wompi._status, "data", None)
    monkeypatch.setitem(wompi._status, "ok_at", 0.0)
    monkeypatch.setattr(wompi, "_refreshing", False)
    gate, calls = _blocked_fetch(monkeypatch, _ok())
    t0 = time.time()
    r = client.post(f"{_url(ev, form)}/quote", json={"values": {}})
    assert r.status_code == 200 and time.time() - t0 < 2 and "service" not in r.json()          # no esperó a Wompi (la consulta sigue bloqueada)
    gate.set()
    _wait_idle()
    assert client.post(f"{_url(ev, form)}/quote", json={"values": {}}).json()["service"] == {"indicator": "minor", "description": "Degraded"}      # y la siguiente ya trae el aviso
