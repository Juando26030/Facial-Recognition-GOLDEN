"""Apellido obligatorio o no, detectado por la base cargada (Fase 2; app/lastname.py).
Detección (solo nombre / nombre+apellido / mixta), lo manual manda sobre lo automático, validación del servidor (alta, edición, bandeja sin red) y regresión: evento sin dato = comportamiento de siempre."""
import pytest

from app import lastname
from app.models import User
from tests.test_person_form import _admin, _design, _op, _sync


@pytest.fixture
def pf_on(monkeypatch):
    monkeypatch.setenv("PERSON_FORM_ENABLED", "1")


def _rows(n, with_last, col=True):
    out = []
    for i in range(n):
        r = {"id": str(1000 + i), "nombres": f"Persona {i}"}
        if col:
            r["apellidos"] = f"Apellido {i}" if i < with_last else ""
        out.append(r)
    return out


# ------------------------------------------------------------------------------------------------------------------ detección pura
def test_detect_name_only_base_is_not_using_last_name():
    d = lastname.detect([{"id": "1", "nombres": "Ana Pérez Gómez"}, {"id": "2", "nombres": "Luis Mora"}], {"id": "A", "nombres": "B"})
    assert d == {"uses": False, "total": 2, "with_last": 0}


def test_detect_separate_columns_is_using_last_name():
    d = lastname.detect(_rows(10, 10), {"id": "A", "nombres": "B", "apellidos": "C"})
    assert d["uses"] is True and d["with_last"] == 10


def test_detect_mixed_base_uses_the_half_threshold():
    assert lastname.detect(_rows(10, 5), {"apellidos": "C"})["uses"] is True, "justo la mitad ya cuenta"
    assert lastname.detect(_rows(10, 4), {"apellidos": "C"})["uses"] is False
    assert lastname.detect(_rows(10, 0), {"apellidos": "C"})["uses"] is False, "columna presente pero vacía"


def test_detect_ignores_rows_without_id_and_returns_none_without_people():
    rows = _rows(4, 4) + [{"id": "", "nombres": "x", "apellidos": ""}] * 20
    assert lastname.detect(rows, {"apellidos": "C"})["uses"] is True
    assert lastname.detect([{"id": "", "nombres": "x"}], {}) is None and lastname.detect([], {}) is None


def test_missing_message():
    assert lastname.missing_message(True, "  ") and lastname.missing_message(True, None)
    assert lastname.missing_message(True, "Pérez") is None and lastname.missing_message(False, "") is None


# ------------------------------------------------------------------------------------------------------------------ estado guardado
def test_event_without_data_keeps_the_current_behaviour(client, factory, db):
    ev = factory.event("en_proceso")
    st = lastname.state(db, ev.id)
    assert st["required"] is False and st["source"] == "default"


def test_manual_beats_auto_and_none_goes_back_to_auto(client, factory, db):
    ev = factory.event("en_proceso")
    lastname.record_detection(db, ev, {"uses": True, "total": 10, "with_last": 9})
    assert lastname.state(db, ev.id)["required"] is True and lastname.state(db, ev.id)["source"] == "auto"
    lastname.set_manual(db, ev, False)
    assert lastname.state(db, ev.id) == {**lastname.state(db, ev.id), "required": False, "source": "manual", "auto": True}
    lastname.record_detection(db, ev, {"uses": True, "total": 12, "with_last": 12})          # otra carga: lo manual sigue mandando
    assert lastname.state(db, ev.id)["required"] is False
    lastname.set_manual(db, ev, None)
    assert lastname.state(db, ev.id)["required"] is True and lastname.state(db, ev.id)["source"] == "auto"


def test_bulk_load_detects_and_saves_the_setting(client, factory, db):
    _admin(client, factory)
    ev = factory.event("creado")
    csv = "cédula,nombres,apellidos\n1,Ana,Pérez\n2,Luis,Mora\n3,Eva,Ríos\n".encode()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("b.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    assert lastname.state(db, ev.id)["required"] is True
    ev2 = factory.event("creado")
    csv2 = "cédula,nombre completo\n1,Ana Pérez\n2,Luis Mora\n".encode()
    assert client.post("/api/bulk_register", data={"event_id": str(ev2.id)}, files={"roster_file": ("b.csv", csv2, "text/csv")}).status_code == 200
    st = lastname.state(db, ev2.id)
    assert st["required"] is False and st["auto"] is False and st["source"] == "auto"


# ------------------------------------------------------------------------------------------------------------------ Parámetros y validación del servidor
def test_parametros_endpoint_sets_manual_mode_and_field_configs_follow(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    cfg = lambda: next(c for c in client.get(f"/api/events/{ev.id}/field-configs").json() if c["key"] == "last_name")  # noqa: E731
    assert cfg()["required"] is False
    assert client.put(f"/api/events/{ev.id}/last-name-required", json={"mode": "required"}).json()["source"] == "manual"
    assert cfg()["required"] is True
    assert client.put(f"/api/events/{ev.id}/last-name-required", json={"mode": "optional"}).json()["required"] is False
    assert client.put(f"/api/events/{ev.id}/last-name-required", json={"mode": "auto"}).json()["source"] == "default"
    assert client.put(f"/api/events/{ev.id}/last-name-required", json={"mode": "x"}).status_code == 400


def test_register_without_last_name_is_blocked_only_when_required(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    ok = client.post("/api/register", data={"event_id": ev.id, "id": "7001", "first_name": "Ana María Pérez"})
    assert ok.status_code == 200 and db.query(User).filter_by(id="7001").one().last_name == "", "sin dato guardado: como siempre"
    lastname.set_manual(db, ev, True)
    db.commit()
    bad = client.post("/api/register", data={"event_id": ev.id, "id": "7002", "first_name": "Luis"})
    assert bad.status_code == 400 and "apellido" in bad.json()["detail"].lower()
    assert db.query(User).filter_by(id="7002").first() is None
    good = client.post("/api/register", data={"event_id": ev.id, "id": "7002", "first_name": "Luis", "last_name": "Mora"})
    assert good.status_code == 200
    lastname.set_manual(db, ev, False)
    db.commit()
    assert client.post("/api/register", data={"event_id": ev.id, "id": "7003", "first_name": "Eva"}).status_code == 200


def test_edit_cannot_blank_a_required_last_name(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    factory.person(ev, "7100", first_name="Ana", last_name="Pérez")
    lastname.set_manual(db, ev, True)
    db.commit()
    r = client.patch(f"/api/users/7100?event_id={ev.id}", json={"last_name": ""})
    assert r.status_code == 400 and "apellido" in r.json()["detail"].lower()
    assert client.patch(f"/api/users/7100?event_id={ev.id}", json={"last_name": "Gómez"}).status_code == 200
    lastname.set_manual(db, ev, False)
    db.commit()
    assert client.patch(f"/api/users/7100?event_id={ev.id}", json={"last_name": ""}).status_code == 200


def test_outbox_create_validates_last_name_when_required(client, factory, db):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    lastname.set_manual(db, ev, True)
    db.commit()
    res = _sync(client, ev, _op("a1", id="7200", first_name="Nora"), _op("a2", id="7201", first_name="Nora", last_name="Sol")).json()["results"]
    assert res[0]["result"] == "error" and "Apellidos" in res[0]["detail"]
    assert res[1]["result"] == "ok"
    lastname.set_manual(db, ev, False)
    db.commit()
    assert _sync(client, ev, _op("a3", id="7202", first_name="Nora")).json()["results"][0]["result"] == "ok"


def test_person_form_shows_the_event_rule_and_bumps_the_version(client, factory, db, pf_on):
    _admin(client, factory)
    ev = factory.event("en_proceso")
    d = _design(ev, client).json()["definition"]
    assert d["fields"]["last_name"]["required"] is False
    client.put(f"/api/events/{ev.id}/last-name-required", json={"mode": "required"})
    v2 = client.get(f"/api/events/{ev.id}/person-form").json()["definition"]
    assert v2["fields"]["last_name"]["required"] is True and v2["form_version"] == d["form_version"] + 1, "la copia sin red anterior queda como vieja"
    assert _design(ev, client, fields={"last_name": {"required": False}}).json()["definition"]["fields"]["last_name"]["required"] is True, "el diseño no manda sobre el evento"
    old = _sync(client, ev, _op("b1", version=d["form_version"], id="7300", first_name="Sin Apellido")).json()["results"][0]
    assert old["result"] == "ok" and old.get("warnings"), "copia anterior: se guarda y se avisa"
    now = _sync(client, ev, _op("b2", version=v2["form_version"], id="7301", first_name="Sin Apellido")).json()["results"][0]
    assert now["result"] == "error"
