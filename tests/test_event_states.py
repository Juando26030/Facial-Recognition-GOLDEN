"""Estados de evento configurables con reglas (docs/18 §4): CRUD solo para administrador, valores por defecto que reproducen el comportamiento de siempre, reglas propias que abren o cierran
el acceso del cliente, de los digitadores temporales y el registro, y el cambio de estado de un evento (el estado base sigue mandando)."""
import pytest
from fastapi import HTTPException

from app import auth, event_rules
from app.models import Event, EventState
from tests.conftest import login


def _state(db, name, base, **rules):
    import json
    s = EventState(name=name, base_status=base, position=db.query(EventState).count(), rules_json=json.dumps(rules))
    db.add(s)
    db.commit()
    return s


def _users_status(client, ev):
    return client.get(f"/api/users?event_id={ev.id}").status_code


# ------------------------------------------------------------------ valores por defecto = comportamiento de siempre
@pytest.mark.parametrize("status,digitador_ok,registration_ok", [("creado", False, False), ("en_proceso", True, True), ("finalizado", False, False)])
def test_defaults_by_base_status_reproduce_the_old_behaviour(client, factory, status, digitador_ok, registration_ok):
    factory.staff("admin", "root")
    dig, cli = factory.staff("digitador", "dig"), factory.staff("cliente", "cli")
    ev = factory.event(status)
    factory.authorize(ev, dig)
    factory.authorize(ev, cli)
    login(client, "dig")
    assert (_users_status(client, ev) == 200) is digitador_ok
    login(client, "cli")
    assert (_users_status(client, ev) != 403) is digitador_ok or status != "en_proceso"
    if registration_ok:
        auth.require_event_in_progress(ev)
    else:
        with pytest.raises(HTTPException) as exc:
            auth.require_event_in_progress(ev)
        assert exc.value.status_code == 403 and ("todavía no ha comenzado" in exc.value.detail or "ya está finalizado" in exc.value.detail)


# ------------------------------------------------------------------ reglas propias
def test_a_custom_state_can_let_temporary_digitadores_in_before_the_event_starts_without_opening_registration(client, factory, db):
    factory.staff("admin", "root")
    dig = factory.staff("digitador", "dig")
    montaje = _state(db, "Montaje", "creado", temp_digitadores_enter=True)
    ev = factory.event("creado", state_id=montaje.id)
    factory.authorize(ev, dig)
    login(client, "dig")
    assert _users_status(client, ev) == 200                                                  # entra aunque el evento no ha comenzado
    with pytest.raises(HTTPException) as exc:
        auth.require_event_in_progress(ev)                                                   # pero registrar sigue cerrado (la regla «registration» no se abrió)
    assert exc.value.status_code == 403 and "Montaje" in exc.value.detail                   # y el mensaje nombra el estado


def test_a_custom_finished_state_can_keep_the_client_in_to_download_the_report(client, factory, db):
    factory.staff("admin", "root")
    cli = factory.staff("cliente", "cli")
    informe = _state(db, "Entrega de informe", "finalizado", client_access=True, client_stats_download=True)
    ev = factory.event("finalizado", state_id=informe.id)
    factory.authorize(ev, cli)
    login(client, "cli")
    assert _users_status(client, ev) != 403
    assert event_rules.allowed(ev, "client_stats_download") is True
    plain = factory.event("finalizado")
    factory.authorize(plain, cli)
    login(client, "cli")
    assert _users_status(client, plain) == 403                                              # sin estado propio: como siempre


def test_a_state_can_close_what_the_base_status_opens(client, factory, db):
    factory.staff("admin", "root")
    dig = factory.staff("digitador", "dig")
    pausa = _state(db, "En pausa", "en_proceso", temp_digitadores_enter=False, registration=False)
    ev = factory.event("en_proceso", state_id=pausa.id)
    factory.authorize(ev, dig)
    login(client, "dig")
    assert _users_status(client, ev) == 403
    with pytest.raises(HTTPException):
        auth.require_event_in_progress(ev)
    assert event_rules.allowed(ev, "roulette") is True                                       # lo que el estado no dice vale lo del estado base
    with pytest.raises(KeyError):
        event_rules.allowed(ev, "no-existe")


# ------------------------------------------------------------------ CRUD
def test_only_admins_manage_states_but_everyone_logged_in_reads_them(client, factory, db):
    factory.staff("admin", "root")
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/event-states").status_code == 200
    assert client.post("/api/event-states", json={"name": "X", "base_status": "creado"}).status_code == 403
    login(client, "root")
    r = client.post("/api/event-states", json={"name": "Montaje", "base_status": "creado", "color": "#ff9900", "rules": {"temp_digitadores_enter": True, "inventada": True}})
    assert r.status_code == 200
    body = r.json()
    assert body["rules"]["temp_digitadores_enter"] is True and "inventada" not in body["rules"] and body["rules"]["registration"] is False          # solo reglas conocidas; el resto, del estado base
    listing = client.get("/api/event-states").json()
    assert {"client_access", "temp_digitadores_enter", "registration"} <= {r["key"] for r in listing["rules"]} and listing["base_statuses"] == ["creado", "en_proceso", "finalizado"]
    assert client.post("/api/event-states", json={"name": " montaje ", "base_status": "creado"}).status_code == 400         # nombre repetido (sin importar mayúsculas)
    assert client.post("/api/event-states", json={"name": "Raro", "base_status": "otro"}).status_code == 400
    assert client.post("/api/event-states", json={"name": "  ", "base_status": "creado"}).status_code == 400
    sid = body["id"]
    assert client.patch(f"/api/event-states/{sid}", json={"name": "Montaje y pruebas", "rules": {"roulette": False}}).json()["name"] == "Montaje y pruebas"
    assert client.post(f"/api/event-states/{sid}/archive").status_code == 400                # es el único activo con ese estado base
    assert client.post("/api/event-states", json={"name": "Preparación", "base_status": "creado"}).status_code == 200
    assert client.post(f"/api/event-states/{sid}/archive").status_code == 200                # Fase 3: se archiva (admin); borrar de verdad es de super_admin y de lo archivado
    assert client.delete(f"/api/event-states/{sid}").status_code == 403
    assert client.get("/api/event-states").json()["states"][0]["name"] == "Preparación"


def test_a_state_in_use_cannot_change_base_be_disabled_or_deleted(client, factory, db):
    factory.staff("admin", "root")
    a, b = _state(db, "A", "creado"), _state(db, "B", "creado")
    ev = factory.event("creado", state_id=a.id)
    login(client, "root")
    assert client.patch(f"/api/event-states/{a.id}", json={"base_status": "en_proceso"}).status_code == 400
    assert client.patch(f"/api/event-states/{a.id}", json={"is_active": False}).status_code == 400
    assert client.post(f"/api/event-states/{a.id}/archive").status_code == 400
    assert client.patch(f"/api/event-states/{b.id}", json={"base_status": "en_proceso"}).json()["base_status"] == "en_proceso"        # sin eventos sí
    assert db.get(Event, ev.id).state_id == a.id


# ------------------------------------------------------------------ cambiar el estado de un evento
def test_changing_an_events_state_moves_its_base_status_and_a_plain_status_change_picks_the_default_state(client, factory, db):
    factory.staff("admin", "root")
    creado = _state(db, "Creado", "creado")
    montaje = _state(db, "Montaje", "creado")
    proceso = _state(db, "En proceso", "en_proceso")
    cierre = _state(db, "Cierre", "finalizado")
    ev = factory.event("creado", state_id=creado.id)
    login(client, "root")
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": montaje.id})
    assert r.status_code == 200 and r.json()["state_name"] == "Montaje" and r.json()["status"] == "creado"
    r = client.patch(f"/api/events/{ev.id}", json={"state_id": cierre.id})
    assert r.json()["status"] == "finalizado" and r.json()["state_id"] == cierre.id                                          # el estado base manda el comportamiento
    r = client.patch(f"/api/events/{ev.id}", json={"status": "en_proceso"})
    assert r.status_code == 200 and r.json()["state_id"] == proceso.id and r.json()["state_name"] == "En proceso"             # solo cambió el estado base: primer estado de ese tipo
    montaje.is_active = False
    db.commit()
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": montaje.id}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}", json={"state_id": 99999}).status_code == 400
    assert client.patch(f"/api/events/{ev.id}", json={"name": "Otro nombre"}).json()["state_id"] == proceso.id                # editar otra cosa no toca el estado


def test_new_events_start_in_the_first_created_state(client, factory, db):
    factory.staff("admin", "root")
    factory.staff("comercial", "com")
    coord = factory.staff("coordinador", "coord")
    factory.tenant("acme")
    inicial = _state(db, "Creado", "creado")
    login(client, "root")
    r = client.post("/api/events", json={"tenant_id": "acme", "event_code": "N1", "name": "Nuevo", "location": "L", "address": "D", "country": "CO", "city": "Bogotá", "start_date": "2026-11-01", "end_date": "2026-11-02", "setup_date": "2026-10-31",
                                      "event_time_start": "08:00", "event_time_end": "18:00", "setup_time_start": "06:00", "setup_time_end": "07:00", "coordinator_staff_id": coord.id,
                                      "commercial_staff_id": factory.staff("comercial").id})
    assert r.status_code == 200, r.text
    assert r.json()["state_id"] == inicial.id and r.json()["status"] == "creado"
