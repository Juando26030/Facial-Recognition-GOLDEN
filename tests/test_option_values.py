"""P7: «Usar los valores que ya están en la base» — agrupación de variantes, tope, campos bloqueados y permisos por rol."""
import json

import pytest

from app import optionvalues as ov
from app.models import EventAttendee, User
from tests.conftest import login


# ------------------------------------------------------------------ lógica pura
def test_groups_variants_without_repeats_and_sorted():
    r = ov.group_values({"Bogotá": 5, "Bogota": 2, " bogotá ": 1, "Apartadó": 3, "": 9, "cali": 1})
    assert [g["suggested"] for g in r["groups"]] == ["Apartadó", "Bogotá", "cali"]                  # A–Z, sin repetidos
    bog = r["groups"][1]
    assert [v["value"] for v in bog["values"]] == ["Bogotá", "Bogota", "bogotá"] and bog["count"] == 8      # variantes juntas para elegir
    assert r["total"] == 3 and not r["truncated"]


def test_suggested_prefers_accents_on_a_tie():
    assert ov.group_values({"Medellin": 2, "Medellín": 2})["groups"][0]["suggested"] == "Medellín"


def test_cap_keeps_the_most_frequent_and_warns():
    counts = {f"Ciudad {i:03d}": i + 1 for i in range(250)}
    r = ov.group_values(counts)
    assert len(r["groups"]) == ov.LIMIT == 200 and r["truncated"] and r["total"] == 250
    assert "Ciudad 249" in [g["suggested"] for g in r["groups"]] and "Ciudad 000" not in [g["suggested"] for g in r["groups"]]
    assert [g["suggested"] for g in r["groups"]] == sorted(g["suggested"] for g in r["groups"])      # y sale en orden alfabético


def test_too_long_values_are_skipped():
    r = ov.group_values({"x" * 121: 1, "ok": 1})
    assert [g["suggested"] for g in r["groups"]] == ["ok"] and r["skipped"] == 1


@pytest.mark.parametrize("key", ["id", "first_name", "last_name", "email", "phone", "birth_date", "digital_contact", "certificate", "x", "opcional_x", ""])
def test_identifying_fields_are_blocked(key):
    with pytest.raises(ValueError):
        ov.check_key(key, "lo que sea")


@pytest.mark.parametrize("label", ["Celular alterno", "Correo personal", "Número de documento", "Nombre del acudiente", "Fecha de nacimiento", "Dirección"])
def test_optional_fields_that_look_personal_are_blocked(label):
    with pytest.raises(ValueError):
        ov.check_key("opcional_3", label)


def test_allowed_fields():
    for key, label in (("role", "Cargo"), ("entity", "Entidad"), ("opt_1", "Tipo"), ("categories", "Categoría"), ("opcional_1", "Ciudad"), ("opcional_12", "Talla")):
        ov.check_key(key, label)


# ------------------------------------------------------------------ endpoint
def _people(db, ev, rows, event_id=None):
    for i, (uid, city) in enumerate(rows):
        u = db.query(User).filter_by(id=uid, tenant_id=ev.tenant_id).first() or User(id=uid, tenant_id=ev.tenant_id, first_name=f"Nombre{i}", last_name="X", entity="Org", extra_fields=json.dumps({"opcional_1": city, "opcional_2": "3001112222"}))
        db.merge(u)
        db.flush()
        db.add(EventAttendee(event_id=event_id or ev.id, user_id=uid, tenant_id=ev.tenant_id))
    db.commit()


def _setup(factory, db):
    coord = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=coord, optional_field_labels=json.dumps({"opcional_1": "Ciudad", "opcional_2": "Celular alterno"}))
    other = factory.event("en_proceso", coordinator=coord)
    _people(db, ev, [("1", "Bogotá"), ("2", "Bogota"), ("3", "Apartadó")])
    _people(db, other, [("4", "Cali"), ("5", "Bogotá")])
    return ev


def test_returns_only_values_with_counts_never_people(client, factory, db):
    ev = _setup(factory, db)
    login(client, "coord1")
    r = client.get(f"/api/events/{ev.id}/field-values", params={"key": "opcional_1"})
    assert r.status_code == 200
    body = r.json()
    assert [g["suggested"] for g in body["groups"]] == ["Apartadó", "Bogotá"] and body["scope"] == "event"
    assert sorted(body) == ["groups", "key", "label", "limit", "scope", "skipped", "total", "truncated"]      # nada de registros de personas
    assert "Nombre0" not in r.text and "3001112222" not in r.text and '"1"' not in r.text


def test_scope_client_includes_other_events_of_the_same_client(client, factory, db):
    ev = _setup(factory, db)
    login(client, "coord1")
    body = client.get(f"/api/events/{ev.id}/field-values", params={"key": "opcional_1", "scope": "client"}).json()
    assert [g["suggested"] for g in body["groups"]] == ["Apartadó", "Bogotá", "Cali"] and body["scope"] == "client"


def test_blocked_fields_return_400(client, factory, db):
    ev = _setup(factory, db)
    login(client, "coord1")
    for key in ("id", "first_name", "email", "phone", "birth_date", "opcional_2"):             # opcional_2 se llama «Celular alterno»
        r = client.get(f"/api/events/{ev.id}/field-values", params={"key": key})
        assert r.status_code in (400, 404), key
        assert "3001112222" not in r.text
    assert client.get(f"/api/events/{ev.id}/field-values", params={"key": "opcional_2"}).status_code == 400


def test_roles(client, factory, db):
    ev = _setup(factory, db)
    factory.staff("digitador", "dig1")
    factory.staff("cliente", "cli1")
    url = f"/api/events/{ev.id}/field-values"
    assert client.get(url, params={"key": "opcional_1"}).status_code in (401, 403)          # sin sesión
    login(client, "dig1")
    assert client.get(url, params={"key": "opcional_1"}).status_code == 403
    login(client, "cli1")
    assert client.get(url, params={"key": "opcional_1"}).status_code == 403
    login(client, "coord1")
    assert client.get(url, params={"key": "opcional_1"}).status_code == 200
    factory.staff("admin", "adm1")
    login(client, "adm1")
    assert client.get(url, params={"key": "opcional_1"}).status_code == 200
