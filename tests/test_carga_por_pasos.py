"""Carga masiva POR PASOS (orden del 24-oct-2026): cada paso dentro de su petición, reanudable, idempotente, con un máximo FIJO de consultas por petición, sin red ni progreso por fila, con lo
temporal cifrado y borrado. Ninguna prueba depende del orden ni de la colación de la base (las listas se comparan en Python)."""
import json
import socket
import threading
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event

from app import bulk_jobs, bulk_steps, crypto
from app.database import engine
from app.models import BulkJob, EventAttendee, StaffUser, User
from app.storage import get_storage
from tests import _golden_load as G
from tests.conftest import PASSWORD, login
from tests.test_rendimiento import GOLDEN, SqlCount, _rows

MAX_QUERIES_PER_REQUEST = 60          # tope FIJO por petición, igual con 1.000 que con 8.000 filas


def _post(client, ev, data, **extra):
    return client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true", **extra}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})


def _drive(client, first, limit=200):
    """Hace lo que hace el navegador: pide un paso tras otro hasta que termina. Devuelve (estado final, cuántas peticiones de paso hizo)."""
    st, calls = first, 0
    while st["status"] not in ("done", "error") and calls < limit:
        st = client.post(f"/api/bulk_jobs/{first['job_id']}/step").json()
        calls += 1
    return st, calls


@pytest.fixture()
def coord(client, factory):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    return ev


@pytest.fixture()
def small_steps(monkeypatch):
    monkeypatch.setattr(bulk_steps, "STEP_ROWS", 3)
    monkeypatch.setattr(bulk_steps, "SYNC_ROWS", 0)


# ---------------------------------------------------------------------------------------------------- (a) idéntico a main
def test_steps_give_exactly_the_result_of_the_previous_code(client, factory, db, small_steps):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    G.prepare(db, ev)
    first = _post(client, ev, G.xlsx_bytes(), field_labels=json.dumps({"opcional_1": "Talla"})).json()
    assert first["mode"] == "steps" and first["status"] == "running" and first["total"] == 10
    final, calls = _drive(client, first)
    assert final["status"] == "done" and calls == 4                                   # 10 filas de a 3 = 4 pasos
    got = G.dump(db, ev, final["result"])
    again = _drive(client, _post(client, ev, G.xlsx_bytes()).json())[0]               # el mismo archivo otra vez (reintento)
    got["retry"] = G.dump(db, ev, again["result"])
    want = json.load(open(GOLDEN, encoding="utf-8"))
    assert json.loads(json.dumps(got, sort_keys=True)) == want                         # mismos registros, mismos errores y mensajes que main


# ---------------------------------------------------------------------------------------------------- (b) consultas por petición: tope fijo
@pytest.mark.parametrize("rows", [1000, 8000])
def test_every_request_of_a_load_stays_under_a_fixed_number_of_queries_whatever_the_rows(client, coord, db, rows):
    data = G.xlsx_bytes(_rows(rows))
    worst = 0
    for repeat in range(2):                                                             # 1.ª carga: personas nuevas; 2.ª: las mismas, que ya existen (el caso de la consulta de rostro por fila)
        with SqlCount() as q:
            first = _post(client, coord, data).json()
        worst = max(worst, q.n)
        st, calls = first, 0
        while st["status"] not in ("done", "error"):
            with SqlCount() as q:
                st = client.post(f"/api/bulk_jobs/{first['job_id']}/step").json()
            worst = max(worst, q.n)
            calls += 1
        assert st["status"] == "done" and st["result"]["count"] == rows
        assert calls == -(-rows // bulk_steps.STEP_ROWS) if rows > bulk_steps.SYNC_ROWS else True
    assert worst <= MAX_QUERIES_PER_REQUEST, worst
    db.expire_all()
    assert db.query(User).filter_by(tenant_id=coord.tenant_id).count() == rows and db.query(EventAttendee).filter_by(event_id=coord.id).count() == rows     # repetir no duplica


# ---------------------------------------------------------------------------------------------------- (c) nada de red ni progreso por fila
def test_no_network_no_storage_call_and_no_progress_write_per_row(client, coord, db, monkeypatch):
    rows = 3000
    data = G.xlsx_bytes(_rows(rows))
    st = get_storage()
    calls = {}
    for name in ("exists", "get", "put", "list", "delete", "delete_prefix"):
        real = getattr(type(st), name)
        monkeypatch.setattr(type(st), name, (lambda real, name: lambda self, *a, **k: (calls.__setitem__(name, calls.get(name, 0) + 1), real(self, *a, **k))[1])(real, name))
    net = {"n": 0}
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (net.__setitem__("n", net["n"] + 1), (_ for _ in ()).throw(OSError("sin red en la prueba")))[1])
    writes = {"n": 0}

    def count_job_updates(conn, cur, stmt, params, ctx, many):
        if stmt.lstrip().upper().startswith("UPDATE BULK_JOBS"):
            writes["n"] += 1
    sa_event.listen(engine, "before_cursor_execute", count_job_updates)
    try:
        first = _post(client, coord, data).json()
        final, steps = _drive(client, first)
        assert final["status"] == "done" and final["result"]["count"] == rows
        again = _drive(client, _post(client, coord, data).json())[0]                    # y la misma carga otra vez: personas que ya existen
        assert again["status"] == "done"
    finally:
        sa_event.remove(engine, "before_cursor_execute", count_job_updates)
    assert net["n"] == 0                                                                # ni DNS ni red por fila (validar correos/teléfonos es solo un patrón)
    assert sum(calls.get(k, 0) for k in ("exists", "get", "list")) <= 80, calls          # el almacenamiento: unas decenas de llamadas en total, no una por persona
    assert calls.get("put", 0) <= 40 and calls.get("delete_prefix", 0) <= 4, calls
    assert writes["n"] <= 40, writes                                                    # el avance se guarda por paso (y en el alta/cierre de la tarea), nunca por fila


def test_the_progress_callback_is_called_every_fifty_rows_not_every_row(client, coord, db, monkeypatch):
    import app.routers.api as api
    staff = db.query(StaffUser).filter_by(username="coord1").one()
    seen = []
    api._bulk_register_impl(db, staff, event_id=coord.id, roster_filename="p.xlsx", content=G.xlsx_bytes(_rows(2000)), zip_bytes=None, field_labels=None, source_event_id=None,
                            progress=lambda *a, **k: seen.append(a[1]))
    assert 2000 // 50 <= len(seen) <= 2000 // 50 + 5, len(seen)


# ---------------------------------------------------------------------------------------------------- (d) corte a la mitad y reanudar
def test_a_load_cut_in_the_middle_is_resumed_where_it_stopped(client, factory, coord, db, small_steps):
    first = _post(client, coord, G.xlsx_bytes(_rows(10))).json()
    client.post(f"/api/bulk_jobs/{first['job_id']}/step")
    mid = client.post(f"/api/bulk_jobs/{first['job_id']}/step").json()
    assert mid["status"] == "running" and mid["done"] == 6
    # «se cerró la página»: otra sesión del mismo usuario retoma la tarea que quedó a medias
    from app.main import app
    c2 = TestClient(app)
    assert c2.post("/login", data={"username": "coord1", "password": PASSWORD}, follow_redirects=False).status_code in (200, 302, 303)
    active = c2.get(f"/api/bulk_jobs/active?event_id={coord.id}").json()["job"]
    assert active and active["job_id"] == first["job_id"] and active["done"] == 6
    final, _ = _drive(c2, active)
    assert final["status"] == "done" and final["result"]["count"] == 10
    db.expire_all()
    assert db.query(User).filter_by(tenant_id=coord.tenant_id).count() == 10
    assert c2.get(f"/api/bulk_jobs/active?event_id={coord.id}").json()["job"] is None             # ya no hay nada pendiente


def test_a_step_that_fails_in_the_middle_leaves_nothing_and_is_repeated_without_duplicates(client, coord, db, small_steps, monkeypatch):
    """Las filas y el avance se confirman JUNTOS: si el paso se corta (red, reinicio), no queda nada a medias y el reintento procesa el mismo grupo."""
    import app.routers.api as api
    first = _post(client, coord, G.xlsx_bytes(_rows(7))).json()
    real = api._upsert_attendee_cached
    boom = {"on": True}

    def flaky(db_, event_id, user_id, *a, **k):
        if boom["on"] and user_id == "9900000005":                       # a mitad del segundo paso (filas 4–6)
            boom["on"] = False
            raise RuntimeError("se cortó el servicio")
        return real(db_, event_id, user_id, *a, **k)
    monkeypatch.setattr(api, "_upsert_attendee_cached", flaky)
    seen, st, failures = [], first, 0
    for _ in range(20):
        r = client.post(f"/api/bulk_jobs/{first['job_id']}/step")
        if r.status_code != 200:
            failures += 1
            continue
        st = r.json()
        seen.append(st["done"])
        if st["status"] in ("done", "error"):
            break
    assert failures == 0 and st["status"] == "done" and st["result"]["count"] == 7                  # el lote se repite fila por fila y, al no fallar la segunda vez, quedan las 7
    assert seen == sorted(seen)                                                                        # el avance nunca retrocede
    db.expire_all()
    assert db.query(User).filter_by(tenant_id=coord.tenant_id).count() == 7 == db.query(EventAttendee).filter_by(event_id=coord.id).count()      # sin personas sueltas ni duplicadas


# ---------------------------------------------------------------------------------------------------- (e) dos cargas a la vez
def test_a_second_load_while_one_is_running_is_refused_and_two_steps_at_once_do_not_double_process(client, factory, coord, db, small_steps):
    data = G.xlsx_bytes(_rows(12))
    first = _post(client, coord, data).json()
    assert _post(client, coord, data).status_code == 409                               # otra carga del mismo evento: «ya hay una en curso»
    from app.main import app
    clients = []
    for _ in range(3):
        c = TestClient(app)
        assert c.post("/login", data={"username": "coord1", "password": PASSWORD}, follow_redirects=False).status_code in (200, 302, 303)
        clients.append(c)
    results, barrier = [], threading.Barrier(len(clients))

    def go(c):
        barrier.wait()
        for _ in range(8):
            r = c.post(f"/api/bulk_jobs/{first['job_id']}/step")
            results.append(r.status_code)
            if r.status_code == 200 and r.json()["status"] in ("done", "error"):
                break
    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(results) == {200}, results
    db.expire_all()
    job = db.get(BulkJob, first["job_id"])
    assert job.status == "done" and json.loads(job.result_json)["count"] == 12
    assert db.query(User).filter_by(tenant_id=coord.tenant_id).count() == 12 and db.query(EventAttendee).filter_by(event_id=coord.id).count() == 12


# ---------------------------------------------------------------------------------------------------- (g) roles, cifrado y vencimiento
def test_only_the_requester_with_the_right_role_can_step_or_see_the_load(client, factory, coord, db, small_steps):
    first = _post(client, coord, G.xlsx_bytes(_rows(10))).json()
    factory.staff("coordinador", "otro")
    factory.staff("digitador", "dig")
    factory.authorize(coord, db.query(StaffUser).filter_by(username="dig").one())
    for name, expected in (("otro", 404), ("dig", 403)):
        client.cookies.clear()
        login(client, name)
        assert client.post(f"/api/bulk_jobs/{first['job_id']}/step").status_code == expected, name
    client.cookies.clear()
    assert client.post(f"/api/bulk_jobs/{first['job_id']}/step").status_code in (401, 403)
    client.cookies.clear()
    login(client, "coord1")
    assert client.post(f"/api/bulk_jobs/{first['job_id']}/step").status_code == 200                # el que la pidió sí


def test_the_temporary_files_are_encrypted_have_no_personal_name_and_are_deleted_at_the_end(client, coord, db, small_steps, monkeypatch):
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto._cache.clear()
    try:
        data = G.xlsx_bytes(_rows(7))
        first = _post(client, coord, data).json()
        st = get_storage()
        keys = st.list(f"{coord.tenant_id}/bulk_steps/{first['job_id']}")
        assert sorted(k.rsplit("/", 1)[-1] for k in keys) == ["prepared"]
        assert not any(c in k for k in keys for c in ("9900000001", "Nombre0", "Apellido0"))        # el nombre no lleva datos personales
        for k in keys:
            raw = st.get(k)
            assert raw.startswith(crypto.FILE_MAGIC) and b"9900000001" not in raw and b"Nombre0" not in raw      # y el contenido va cifrado
        final, _ = _drive(client, first)
        assert final["status"] == "done"
        assert st.list(f"{coord.tenant_id}/bulk_steps/{first['job_id']}") == []                     # borrado al terminar
    finally:
        crypto._cache.clear()


def test_an_abandoned_load_expires_its_files_are_deleted_and_it_cannot_continue(client, coord, db, small_steps):
    first = _post(client, coord, G.xlsx_bytes(_rows(10))).json()
    st = get_storage()
    prefix = f"{coord.tenant_id}/bulk_steps/{first['job_id']}"
    assert st.list(prefix)
    job = db.get(BulkJob, first["job_id"])
    from datetime import timedelta

    from app.timeutil import utcnow
    job.updated_at = utcnow() - bulk_steps.TTL - timedelta(minutes=1)
    db.commit()
    assert bulk_steps.purge_expired(db) == 1 and st.list(prefix) == []
    r = client.post(f"/api/bulk_jobs/{first['job_id']}/step").json()
    assert r["status"] == "error" and "venció" in r["error"]["detail"] or "abandonó" in r["error"]["detail"]
    from app import ops_runner
    assert "carga(s) abandonada(s)" in ops_runner.purge_reports()


def test_a_small_base_is_loaded_in_the_same_request_and_photos_keep_the_old_path(client, coord, db):
    one = _post(client, coord, G.xlsx_bytes(_rows(300))).json()
    assert one["mode"] == "steps" and one["status"] == "done" and one["result"]["count"] == 300      # hasta 500 filas: todo en la misma petición
    assert get_storage().list(f"{coord.tenant_id}/bulk_steps") == []
    assert bulk_jobs.active_job(db, coord.id) is None


def test_a_file_with_a_format_error_fails_in_the_same_request_and_leaves_nothing(client, coord, db):
    r = _post(client, coord, G.xlsx_bytes([["x", "y"]], head=["columna", "otra"])).json()
    assert r["status"] == "error" and "formato" in r["error"]["detail"]
    assert db.query(User).filter_by(tenant_id=coord.tenant_id).count() == 0
    assert get_storage().list(f"{coord.tenant_id}/bulk_steps") == []


def test_the_labels_question_still_works_with_steps(client, coord, db, small_steps):
    head = G.HEAD[:8] + ["opcional_1"]
    rows = [[f"90{i:02d}", f"N{i}", f"A{i}", "", "", "", "", "", f"Talla {i}"] for i in range(5)]
    r = _post(client, coord, G.xlsx_bytes(rows, head=head)).json()
    assert r["status"] == "done" and r["result"]["result"] == "NEEDS_LABELS" and r["result"]["fields"] == ["opcional_1"]
    ok = _post(client, coord, G.xlsx_bytes(rows, head=head), field_labels=json.dumps({"opcional_1": "Talla"})).json()
    final, _ = _drive(client, ok)
    assert final["status"] == "done" and final["result"]["count"] == 5
    time.sleep(0)


# ---------------------------------------------------------------------------------------------------- llave de cifrado y Cloud Run Job
def test_without_the_encryption_key_the_steps_are_not_used_and_nothing_is_stored_in_clear(client, coord, db, monkeypatch):
    monkeypatch.delenv("BULK_STEPS_ALLOW_CLEAR", raising=False)
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    crypto._cache.clear()
    assert not bulk_steps.key_ready()
    r = _post(client, coord, G.xlsx_bytes(_rows(40)))
    assert r.status_code == 200 and r.json().get("mode") != "steps"                        # camino de siempre (sin archivo temporal propio)
    assert get_storage().list(f"{coord.tenant_id}/bulk_steps") == []
    job = db.get(BulkJob, r.json()["job_id"])
    assert job.spec_json != bulk_steps.KIND
    for _ in range(100):                                                                    # y la carga igual termina
        st = client.get(f"/api/bulk_jobs/{job.id}").json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert st["status"] == "done" and st["result"]["count"] == 40


def test_in_production_without_the_key_the_app_refuses_to_store_the_temporary_file(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("FACE_ENCRYPTION_KEY", raising=False)
    crypto._cache.clear()
    with pytest.raises(crypto.KeyMissing):
        bulk_steps._save("acme", "x" * 32, "prepared", {"rows": [["1001"]]})
    assert get_storage().list("acme/bulk_steps/" + "x" * 32) == []                           # no se escribió nada


def test_with_the_cloud_run_job_backend_the_base_alone_still_goes_by_steps_and_photos_go_to_the_job(client, factory, db, monkeypatch):
    from tests.test_bulk_jobs import _admin, _fake_faces, _photo_zip
    monkeypatch.setenv("BULK_BACKEND", "cloudrun")
    launched = []
    monkeypatch.setattr(bulk_jobs, "launch_cloud_run", launched.append)
    _fake_faces(monkeypatch)
    ev = _admin(client, factory, facial_enabled=True, client_photos_before=True)
    solo = _post(client, ev, G.xlsx_bytes(_rows(30))).json()
    assert solo["mode"] == "steps" and solo["status"] == "done" and solo["result"]["count"] == 30 and launched == []          # sin Job: sin arranque en frío
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true", "photos_authorized": "true"},
                    files={"roster_file": ("b.csv", b"id,nombres,apellidos\n7001,A,B\n", "text/csv"), "zip_file": ("f.zip", _photo_zip(["7001"]), "application/zip")})
    assert r.status_code == 200 and launched == [r.json()["job_id"]]                                                           # con fotos: el Job de siempre
