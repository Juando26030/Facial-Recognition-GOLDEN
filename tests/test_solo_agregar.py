"""«Solo agregar personas nuevas» a un evento en curso (pista Eventos en curso, pedido A): nunca toca a quien ya existe, no crea campos y no estorba al registro en vivo."""
import pytest

from app import event_rules
from app.models import Event


@pytest.mark.parametrize("status, uploaded, normal_blocked, append_blocked", [
    ("finalizado", False, True, True), ("finalizado", True, True, True),
    ("en_proceso", True, True, False), ("en_proceso", False, False, False),
    ("creado", False, False, False), ("creado", True, False, False)])
def test_append_only_is_allowed_in_progress_but_never_finalized(status, uploaded, normal_blocked, append_blocked):
    ev = Event(status=status, roster_uploaded=uploaded)
    assert bool(event_rules.roster_block_reason(ev)) is normal_blocked
    assert bool(event_rules.roster_block_reason(ev, append_only=True)) is append_blocked


# ------------------------------------------------------------------------------------------------------------------------------------ carga
import json

from fastapi.testclient import TestClient  # noqa: E402,F401

from app import roster_append  # noqa: E402
from app.models import AuditConsentLog, EventAttendee, User  # noqa: E402
from tests.conftest import login  # noqa: E402

SHEET = ("id,nombres,apellidos,cargo,entidad,correo,Talla de camiseta,opcional_5,categoria\n"
         "1001,Ana,Nueva,Jefa,Acme,ana@example.com,M,x,General\n"
         "1002,Beto,Nuevo,,,beto@example.com,L,y,VIP-inexistente\n"
         "1001,Ana,Repetida,Otra,Otra,otra@example.com,S,z,General\n"          # repetida en la hoja: gana la primera
         "2001,Pisado,Pisado,Pisado,Pisado,pisado@example.com,XL,w,\n"          # ya está en el evento: NO se toca
         "3001,Cliente,Pisado,Pisado,Pisado,otro@example.com,XL,w,\n"           # existe en el cliente, no en el evento: solo se inscribe
         ",SinCedula,X,,,,,,\n")


def _post_append(client, ev, data=SHEET, **extra):
    body = data.encode("utf-8") if isinstance(data, str) else data
    return client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true", "append_only": "true", **extra}, files={"roster_file": ("n.csv", body, "text/csv")})


def _drive(client, first, limit=200):
    st, calls = first, 0
    while st["status"] not in ("done", "error") and calls < limit:
        st = client.post(f"/api/bulk_jobs/{first['job_id']}/step").json()
        calls += 1
    return st


@pytest.fixture()
def live(client, factory, db):
    """Evento EN PROCESO con la base ya cargada y gente que se registró en vivo."""
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", roster_uploaded=True, event_categories=json.dumps(["General"])) if False else factory.event("en_proceso", roster_uploaded=True)
    ev.set_categories(["General"])
    db.commit()
    for uid in ("2001",):
        factory.person(ev, uid, first_name="Original", last_name="Original")
    factory.person(ev, "3001", first_name="Cliente", last_name="Original", attend=False)          # existe en el cliente (otro evento), no en este
    other = db.query(User).filter_by(id="2001", tenant_id=ev.tenant_id).first()
    other.role, other.email, other.face_encoding = "Cargo original", "original@example.com", "[[0.1]]"
    db.commit()
    login(client, "coord1")
    return ev


def _snapshot_user(db, ev, uid):
    db.expire_all()
    u = db.query(User).filter_by(id=uid, tenant_id=ev.tenant_id).first()
    return (u.first_name, u.last_name, u.role, u.entity, u.email, u.phone, u.face_encoding, u.birth_date, u.get_extras() if hasattr(u, "get_extras") else None)


def test_append_creates_only_new_people_and_touches_nobody_else(client, live, db):
    ev = live
    before = {uid: _snapshot_user(db, ev, uid) for uid in ("2001", "3001")}
    labels_before, cats_before = dict(ev.get_optional_labels()), list(ev.get_categories())
    first = _post_append(client, ev)
    assert first.status_code == 200, first.text
    st = _drive(client, first.json())
    assert st["status"] == "done", st
    rep = st["result"]["append"]
    assert (rep["created"], rep["enrolled_existing"], rep["existing"], rep["duplicates"], rep["errors"]) == (2, 1, 1, 1, 1)
    assert rep["columns_ignored"] == 2 and rep["unknown_categories"] == ["VIP-inexistente"]
    db.expire_all()
    assert {uid: _snapshot_user(db, ev, uid) for uid in ("2001", "3001")} == before            # NADA de las existentes cambió
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="3001").count() == 1      # pero la del cliente quedó inscrita en el evento
    ana = db.query(User).filter_by(id="1001", tenant_id=ev.tenant_id).first()
    assert (ana.first_name, ana.last_name, ana.role, ana.email) == ("Ana", "Nueva", "Jefa", "ana@example.com")          # la primera fila, no la repetida
    beto = db.query(User).filter_by(id="1002", tenant_id=ev.tenant_id).first()
    assert beto.role == "" and beto.entity == "" and db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1002").first().get_categories() == []   # vacío donde la hoja no trae; categoría inexistente ignorada
    assert db.query(EventAttendee).filter_by(event_id=ev.id, user_id="1001").first().get_categories() == ["General"]
    ev2 = db.get(type(ev), ev.id)
    assert dict(ev2.get_optional_labels()) == labels_before and list(ev2.get_categories()) == cats_before          # no se crearon campos ni categorías
    assert "@" not in json.dumps(st) and "1001" not in json.dumps(st) and "Ana" not in json.dumps(st)             # ni cédulas ni nombres ni correos en el informe


def test_uploading_the_same_file_twice_creates_nothing_the_second_time(client, live, db):
    ev = live
    _drive(client, _post_append(client, ev).json())
    n_users, n_att = db.query(User).count(), db.query(EventAttendee).filter_by(event_id=ev.id).count()
    again = _drive(client, _post_append(client, ev).json())["result"]["append"]
    assert again["created"] == 0 and again["enrolled_existing"] == 0 and again["existing"] >= 4
    db.expire_all()
    assert db.query(User).count() == n_users and db.query(EventAttendee).filter_by(event_id=ev.id).count() == n_att


def test_zip_and_source_events_are_rejected_and_finalized_events_refuse(client, live, db):
    ev = live
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true", "append_only": "true"},
                    files={"roster_file": ("n.csv", SHEET.encode(), "text/csv"), "zip_file": ("f.zip", b"PK", "application/zip")})
    assert r.status_code == 400 and r.json()["detail"] == roster_append.ZIP_REJECTED
    assert _post_append(client, ev, source_event_id="5").status_code == 400
    ev.status = "finalizado"
    db.commit()
    assert _post_append(client, ev).status_code == 400


def test_the_normal_load_stays_blocked_in_progress_and_is_not_changed(client, live):
    r = client.post("/api/bulk_register", data={"event_id": str(live.id), "background": "true"}, files={"roster_file": ("n.csv", SHEET.encode(), "text/csv")})
    assert r.json()["status"] == "error" and "EN PROCESO" in r.json()["error"]["detail"]          # por pasos el rechazo viaja en la tarea


def test_append_does_not_need_labels_for_unknown_columns_and_ignores_field_labels(client, live, db):
    st = _drive(client, _post_append(client, live, field_labels=json.dumps({"opcional_5": "Intento"})).json())
    assert st["status"] == "done" and "opcional_5" not in live.get_optional_labels()


# ------------------------------------------------------------------------------------------------------------------------------------ vista previa
def test_preview_counts_and_writes_nothing(client, live, db):
    ev = live
    n_users, n_att, ev_row = db.query(User).count(), db.query(EventAttendee).count(), (ev.roster_uploaded, str(ev.get_optional_labels()), str(ev.get_categories()))
    r = client.post("/api/bulk_roster/preview", data={"event_id": str(ev.id)}, files={"roster_file": ("n.csv", SHEET.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["new"], p["enroll_existing"], p["existing"], p["duplicates"], p["without_id"], p["columns_ignored"], p["rows"]) == (2, 1, 1, 1, 1, 2, 6)
    db.expire_all()
    assert (db.query(User).count(), db.query(EventAttendee).count()) == (n_users, n_att)
    ev2 = db.get(type(ev), ev.id)
    assert (ev2.roster_uploaded, str(ev2.get_optional_labels()), str(ev2.get_categories())) == ev_row
    assert "@" not in json.dumps(p) and "1001" not in json.dumps(p)
    assert client.get("/api/bulk_jobs/x").status_code in (404, 403, 401)          # (no dejó ninguna tarea abierta que consultar)


def test_preview_has_the_same_permissions_as_the_load(client, factory, live):
    for role, expected in (("digitador", 403), ("comercial", 403)):
        factory.staff(role, f"u_{role}")
        client.post("/logout")
        login(client, f"u_{role}")
        r = client.post("/api/bulk_roster/preview", data={"event_id": str(live.id)}, files={"roster_file": ("n.csv", SHEET.encode(), "text/csv")})
        assert r.status_code == expected, (role, r.status_code)
    for role in ("coordinador", "admin", "super_admin"):
        factory.staff(role, f"v_{role}")
        client.post("/logout")
        login(client, f"v_{role}")
        assert client.post("/api/bulk_roster/preview", data={"event_id": str(live.id)}, files={"roster_file": ("n.csv", SHEET.encode(), "text/csv")}).status_code == 200


def test_preview_refuses_finalized_and_missing_file(client, live, db):
    assert client.post("/api/bulk_roster/preview", data={"event_id": str(live.id)}).status_code == 400
    live.status = "finalizado"
    db.commit()
    assert client.post("/api/bulk_roster/preview", data={"event_id": str(live.id)}, files={"roster_file": ("n.csv", SHEET.encode(), "text/csv")}).status_code == 400


# ------------------------------------------------------------------------------------------------------------------------------------ pantalla
def test_the_screen_offers_append_only_when_the_event_is_live_and_the_normal_load_stays_blocked(client, live, db):
    page = client.get(f"/kiosk/{live.id}/roster").text
    assert 'id="appendForm"' in page and "Solo agregar personas nuevas" in page and 'id="rosterBlocked"' in page and "const ROSTER_BLOCKED = true" in page
    assert "/api/bulk_roster/preview" in page and "showConfirm(" in page and "confirm(" not in page.replace("showConfirm(", "").replace("Confirm(", "")
    live.status = "finalizado"
    db.commit()
    assert 'id="appendForm"' not in client.get(f"/kiosk/{live.id}/roster").text


def test_the_screen_does_not_offer_append_in_a_fresh_created_event(client, factory):
    factory.staff("coordinador", "c9")
    ev = factory.event("creado")
    login(client, "c9")
    assert 'id="appendForm"' not in client.get(f"/kiosk/{ev.id}/roster").text
