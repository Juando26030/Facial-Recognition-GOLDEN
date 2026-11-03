"""Política de contraseñas con motivo claro: requisitos como lista única (app/security.py), endpoint /api/password-policy, mensajes de rechazo
en cambio/restablecimiento/alta de personal y paridad con la evaluación en vivo del navegador (tests/js/password_policy_check.js, mismos casos)."""
import json
import pathlib

import pytest

from app import security
from tests.conftest import PASSWORD, login

CASES = json.loads((pathlib.Path(__file__).parent / "js" / "password_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("c", CASES)
def test_shared_cases_match_server_policy(c):
    problem = security.password_problem(c["password"], c.get("username"), strict=c["strict"])
    assert (problem is None) is c["ok"]
    failed = [r["id"] for r in security.password_rules(c["password"], c.get("username"), c["strict"]) if not r["ok"]]
    if not c["ok"]:
        assert failed[0] == c["first_failed"]
        assert problem == next(r["problem"] for r in security.password_rules(c["password"], c.get("username"), c["strict"]) if r["id"] == c["first_failed"])


def test_policy_endpoint_is_public_and_matches_backend(client):
    r = client.get("/api/password-policy")
    assert r.status_code == 200
    body = r.json()
    assert body["min_length"] == security.MIN_PASSWORD_LENGTH and [x["id"] for x in body["rules"]] == ["length", "not_username", "not_common"]
    assert "password" in body["common"]
    strict = client.get("/api/password-policy?strict=1").json()
    assert strict["min_length"] == security.MIN_PASSWORD_LENGTH_CREATED and [x["id"] for x in strict["rules"]][:2] == ["length", "letter_digit"]
    assert all(x["label"] and x["problem"] for x in strict["rules"])


def test_rejection_messages_are_clear_in_spanish(client, factory):
    factory.staff("coordinador", "ana")
    login(client, "ana")
    cases = [
        ({"current": PASSWORD, "password": "corta", "confirm": "corta"}, "al menos 8 caracteres"),
        ({"current": PASSWORD, "password": "password", "confirm": "password"}, "demasiado común"),
        ({"current": PASSWORD, "password": "ana", "confirm": "ana"}, "al menos 8 caracteres"),
        ({"current": PASSWORD, "password": "Nueva#2026x", "confirm": "otra#2026xx"}, "no coinciden"),
        ({"current": PASSWORD, "password": PASSWORD, "confirm": PASSWORD}, "distinta a la actual"),
        ({"current": "mala", "password": "Nueva#2026x", "confirm": "Nueva#2026x"}, "actual no es correcta"),
    ]
    for data, text in cases:
        r = client.post("/cambiar-contrasena", data=data)
        assert r.status_code == 400 and text in r.text, (data, r.text[:300])
    equal_user = client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": "ana12345", "confirm": "ana12345"})
    assert equal_user.status_code == 302


def test_change_page_embeds_live_requirements_without_secrets(client, factory):
    factory.staff("coordinador", "ana")
    login(client, "ana")
    page = client.get("/cambiar-contrasena").text
    assert "data-gw-pwcheck" in page and "data-gw-eye" in page and 'id="gwPolicy"' in page and "password-policy.js" in page
    assert "Prueba#2026" not in page


def test_admin_created_accounts_say_which_requirement_fails(client, factory):
    factory.staff("admin", "root1")
    login(client, "root1")
    base = {"username": "nuevo1", "role": "coordinador", "phone": "3001234567"}
    for pwd, text in (("corta1A", "al menos 10 caracteres"), ("abcdefghijk", "una letra y un número"), ("Colombia2026", "demasiado común")):
        r = client.post("/api/staff", json={**base, "password": pwd})
        assert r.status_code == 400 and text in r.json()["detail"]


def test_login_page_has_eye_toggle_and_no_autofill_of_new_secrets(client):
    page = client.get("/login").text
    assert 'data-gw-eye' in page and "password-policy.js" in page
