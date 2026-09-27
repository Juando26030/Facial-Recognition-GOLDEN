"""Cupo atómico (`form_reserve_slot`, migración 0049): envíos simultáneos al último cupo, a un cupo por variable y de la misma cédula."""
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import FormSubmission
from tests.test_forms import _basic_fields, _create, _design, _event, _open, _put, _status, _submit


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    monkeypatch.setattr("app.routers.forms_public.check_email", lambda e: (True, ""))


def _who(n, **extra):
    return {"cedula": f"80{n:04d}", "nombres": f"P{n}", "apellidos": "Q", "correo": f"p{n}@example.com", **extra}


def _burst(ev, f, payloads):
    """Todos los envíos arrancan a la vez (barrera) para pelear de verdad por la fila del formulario."""
    results, gate = [], threading.Barrier(len(payloads))

    def go(values, sid):
        with TestClient(app, follow_redirects=False) as c:
            gate.wait()
            results.append(_submit(c, ev, f, values, sid=sid).status_code)

    threads = [threading.Thread(target=go, args=p) for p in payloads]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results


def _form(factory, capacity=None, settings=None, extra_fields=()):
    with TestClient(app, follow_redirects=False) as admin:
        ev = _event(admin, factory)
        f = _create(admin, ev)
        if extra_fields or settings:
            assert _put(admin, ev, f, design=_design(_basic_fields() + list(extra_fields)), settings=settings or {}).status_code == 200
        if capacity is not None:
            assert _status(admin, ev, f, capacity=capacity).status_code == 200
        _open(admin, ev, f)
        return ev, f


def test_only_one_of_many_simultaneous_submissions_gets_the_last_slot(factory, db):
    ev, f = _form(factory, capacity=3)
    with TestClient(app, follow_redirects=False) as c:
        assert all(_submit(c, ev, f, _who(n), sid=f"pre{n}").status_code == 200 for n in (1, 2))
    results = _burst(ev, f, [(_who(n), f"s{n}") for n in range(10, 20)])
    assert results.count(200) == 1 and results.count(409) == 9
    assert db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").count() == 3


def test_same_document_sent_simultaneously_is_registered_once(factory, db):
    ev, f = _form(factory)
    results = _burst(ev, f, [(_who(7), f"visita{n}") for n in range(8)])      # misma cédula, distintas visitas
    assert results.count(200) == 1 and results.count(409) == 7
    assert db.query(FormSubmission).filter_by(form_id=f["id"], person_id="800007").count() == 1


def test_variable_quota_is_not_oversold_and_does_not_block_other_options(factory, db):
    cat = {"id": "cat", "type": "select", "label": "Categoría", "options": ["VIP", "General"]}
    rules = {"quotas": {"rules": [{"id": "r1", "label": "VIP", "match": "all", "conds": [{"field": "cat", "op": "equals", "value": "VIP"}], "limit": 1}]}}
    ev, f = _form(factory, settings=rules, extra_fields=[cat])
    results = _burst(ev, f, [(_who(n, cat="VIP"), f"v{n}") for n in range(8)] + [(_who(n, cat="General"), f"g{n}") for n in range(20, 24)])
    assert results.count(200) == 5                                             # 1 VIP + las 4 General
    subs = db.query(FormSubmission).filter_by(form_id=f["id"], status="confirmed").all()
    assert sum('"VIP"' in s.data_json for s in subs) == 1
