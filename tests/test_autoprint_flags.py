"""PR3 (4a, docs/etapa/0A causa A y E): el SERVIDOR dice si se imprime solo (`auto_print`) y si autorregistra (`auto_register`) en cada respuesta de la puerta, y el sondeo del directorio
(`GET /api/users/changes`) trae `flags`. Así una pantalla abierta ANTES de encender el interruptor imprime sin recargar."""
from tests.conftest import login


def _setup(client, factory, **event_flags):
    ev = factory.event("en_proceso", **event_flags)
    staff = factory.staff("digitador", "dig")
    factory.authorize(ev, staff)
    factory.person(ev, "1001", "Ana", "Uno")
    login(client, "dig")
    return ev


def _checkin(client, ev, cid="c-1", **extra):
    return client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001", "client_id": cid, **extra})


def test_checkin_cedula_reports_the_event_flags_in_every_outcome(client, factory, db):
    ev = _setup(client, factory)
    pend = _checkin(client, ev).json()                                           # autorregistro apagado: queda pendiente
    assert pend["result"] == "FOUND_PENDING" and pend["auto_print"] is False and pend["auto_register"] is False
    ev.auto_print_badge, ev.auto_register = True, True                           # el coordinador enciende los interruptores con la pantalla del digitador ya abierta
    db.commit()
    ok = _checkin(client, ev).json()
    assert ok["result"] == "SÍ" and ok["auto_print"] is True and ok["auto_register"] is True
    replay = _checkin(client, ev).json()                                         # reenvío con el mismo client_id: mismo resultado, y las banderas siguen presentes
    assert replay["result"] == "SÍ" and replay.get("replayed") is True and replay["auto_print"] is True and replay["auto_register"] is True
    miss = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "9999"}).json()
    assert miss["result"] == "NO_MATCH" and miss["auto_print"] is True


def test_flags_follow_the_server_not_the_page(client, factory, db):
    """Solo autoimpresión (autorregistro apagado) y al revés: cada respuesta lee el valor ACTUAL del evento."""
    ev = _setup(client, factory, auto_print_badge=True)
    r = _checkin(client, ev, confirm="true").json()
    assert r["result"] == "SÍ" and r["auto_print"] is True and r["auto_register"] is False
    ev.auto_print_badge = False
    db.commit()
    other = factory.person(ev, "1002", "Luis", "Dos")
    r2 = client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": other.id, "confirm": "true"}).json()
    assert r2["result"] == "SÍ" and r2["auto_print"] is False


def test_status_patch_and_undo_report_the_flags(client, factory, db):
    ev = _setup(client, factory, auto_print_badge=True, auto_register=True)
    r = client.patch(f"/api/events/{ev.id}/users/1001/status", json={"status": "registrado"})
    assert r.status_code == 200 and r.json()["auto_print"] is True and r.json()["auto_register"] is True
    factory.person(ev, "1003", "Eva", "Tres")                                    # deshacer una acreditación hecha con client_id
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1003", "client_id": "u-1"}).json()["result"] == "SÍ"
    ev.auto_print_badge = False
    db.commit()
    u = client.post(f"/api/events/{ev.id}/accreditations/undo", json={"client_id": "u-1"})
    assert u.status_code == 200 and u.json()["undone"] is True and u.json()["user_id"] == "1003"
    assert u.json()["auto_print"] is False and u.json()["auto_register"] is True


def test_register_reports_the_flags_new_and_existing_person(client, factory, db):
    ev = _setup(client, factory, auto_print_badge=True)
    new = client.post("/api/register", data={"event_id": ev.id, "id": "5005", "first_name": "Nora", "last_name": "Cinco"}).json()
    assert new["auto_print"] is True and new["auto_register"] is False
    factory.person(ev, "6006", "Raul", "Seis", attend=False)                    # ya existía en el cliente: se registra para este evento
    again = client.post("/api/register", data={"event_id": ev.id, "id": "6006", "first_name": "Raul", "last_name": "Seis"}).json()
    assert again["auto_print"] is True and "existía" in again["message"]


def test_directory_changes_carries_the_flags_so_open_screens_catch_up(client, factory, db):
    ev = _setup(client, factory)
    first = client.get(f"/api/users/changes?event_id={ev.id}").json()
    assert first["flags"] == {"auto_print": False, "auto_register": False}
    ev.auto_print_badge, ev.auto_register = True, True
    db.commit()
    nxt = client.get(f"/api/users/changes?event_id={ev.id}&cursor={first['cursor']}").json()
    assert nxt["users"] == [] and nxt["flags"] == {"auto_print": True, "auto_register": True}          # sin cambios de personas, pero la bandera ya llegó (causas A y E)


def test_flags_do_not_leak_across_events(client, factory):
    ev_on = _setup(client, factory, auto_print_badge=True)
    ev_off = factory.event("en_proceso")
    staff = factory.staff("digitador", "dig2")
    factory.authorize(ev_off, staff)
    login(client, "dig2")
    assert client.get(f"/api/users/changes?event_id={ev_off.id}").json()["flags"]["auto_print"] is False
    login(client, "dig")
    assert client.get(f"/api/users/changes?event_id={ev_on.id}").json()["flags"]["auto_print"] is True
