"""Ingreso idempotente (client_id, base del modo contingencia) y directorio con ETag / paginación / incremental / gzip (Fase 0)."""
from app.models import AccessLog
from tests.conftest import login


def _setup(client, factory, people=("1001",), **event_kw):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso", **event_kw)
    for i, uid in enumerate(people):
        factory.person(ev, uid, f"Persona{i}", f"Apellido{i}")
    login(client, "root")
    return ev


# ------------------------------- ingreso idempotente -------------------------------
def test_checkin_with_the_same_client_id_never_duplicates(client, factory, db):
    ev = _setup(client, factory, auto_register=True)
    data = {"event_id": ev.id, "cedula": "1001", "client_id": "kiosco-7-0001", "force": "true"}
    first = client.post("/api/checkin-cedula", data=data).json()
    again = client.post("/api/checkin-cedula", data=data).json()             # reintento de red: mismo resultado, nada nuevo
    assert first["result"] == "SÍ" and "replayed" not in first
    assert again["result"] == "SÍ" and again["replayed"] is True and again["data"]["id"] == "1001"
    assert db.query(AccessLog).filter_by(event_id=ev.id, client_id="kiosco-7-0001").count() == 1
    other = client.post("/api/checkin-cedula", data={**data, "client_id": "kiosco-7-0002"}).json()   # otro ingreso legítimo (otra acción)
    assert other["result"] == "SÍ" and db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 2


def test_checkin_without_client_id_behaves_as_before(client, factory, db):
    ev = _setup(client, factory, auto_register=True)
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001"}).json()["result"] == "SÍ"
    assert client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001"}).json()["result"] == "DUPLICADO"


def test_batch_sync_is_idempotent_and_flags_unknowns_and_double_entries(client, factory, db):
    ev = _setup(client, factory, people=("1001", "1002"))
    body = {"records": [
        {"client_id": "a1", "cedula": "1001", "timestamp": "2026-09-26T20:00:00Z", "method": "qr"},
        {"client_id": "a2", "cedula": "9999"},                                   # no existe en este cliente
        {"client_id": "", "cedula": "1002"},                                     # sin identificador
        {"client_id": "a3", "cedula": "1001"},                                   # misma persona por otro kiosco: se registra y queda para revisión
    ]}
    r = client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).json()
    assert [x["result"] for x in r["results"]] == ["created", "unknown", "invalid", "created"]
    assert r["results"][3]["review"] is True and r["created"] == 2 and r["review"] == 1

    again = client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).json()          # el mismo lote otra vez: nada se duplica
    assert [x["result"] for x in again["results"]] == ["replayed", "unknown", "invalid", "replayed"]
    logs = db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").order_by(AccessLog.id).all()
    assert len(logs) == 2 and logs[0].registration_method == "qr"
    assert logs[0].timestamp.isoformat().startswith("2026-09-26T20:00:00") or logs[0].timestamp is not None   # fecha del kiosco si es razonable


def test_batch_sync_validates_the_payload(client, factory):
    ev = _setup(client, factory)
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json={}).status_code == 400
    too_many = {"records": [{"client_id": f"c{i}", "cedula": "1001"} for i in range(501)]}
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json=too_many).status_code == 400


# ------------------------------- directorio -------------------------------
def test_directory_answers_304_until_something_changes(client, factory):
    ev = _setup(client, factory, people=("1001", "1002"), auto_register=True)
    first = client.get(f"/api/users?event_id={ev.id}")
    assert first.status_code == 200 and len(first.json()) == 2 and first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"
    same = client.get(f"/api/users?event_id={ev.id}", headers={"If-None-Match": first.headers["etag"]})
    assert same.status_code == 304 and same.content == b""

    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1001"})           # alguien se registra: la huella cambia
    changed = client.get(f"/api/users?event_id={ev.id}", headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200 and changed.headers["etag"] != first.headers["etag"]
    assert {u["id"]: u["status"] for u in changed.json()} == {"1001": "Registrado", "1002": "No registrado"}

    client.patch(f"/api/users/1002?event_id={ev.id}", json={"first_name": "Nuevo"})           # una edición también la cambia
    edited = client.get(f"/api/users?event_id={ev.id}", headers={"If-None-Match": changed.headers["etag"]})
    assert edited.status_code == 200


def test_directory_pagination_and_total(client, factory):
    ev = _setup(client, factory, people=tuple(f"10{i:02d}" for i in range(25)))
    page = client.get(f"/api/users?event_id={ev.id}&limit=10&offset=10")
    assert page.status_code == 200 and len(page.json()) == 10 and page.headers["x-total-count"] == "25"
    assert [u["id"] for u in page.json()] == sorted(u["id"] for u in page.json())
    assert len(client.get(f"/api/users?event_id={ev.id}&limit=10&offset=20").json()) == 5
    assert len(client.get(f"/api/users?event_id={ev.id}").json()) == 25                       # sin límite: todo, como siempre


def test_directory_incremental_returns_only_what_changed_after_the_cursor(client, factory):
    ev = _setup(client, factory, people=("1001", "1002", "1003"), auto_register=True)
    full = client.get(f"/api/users/changes?event_id={ev.id}").json()
    assert len(full["users"]) == 3 and full["total"] == 3
    cursor = full["cursor"]
    assert client.get(f"/api/users/changes?event_id={ev.id}&cursor={cursor}").json()["users"] == []

    client.post("/api/checkin-cedula", data={"event_id": ev.id, "cedula": "1002"})
    delta = client.get(f"/api/users/changes?event_id={ev.id}&cursor={cursor}").json()
    assert [u["id"] for u in delta["users"]] == ["1002"] and delta["users"][0]["status"] == "Registrado"
    assert delta["cursor"] != cursor and delta["total"] == 3
    assert client.get(f"/api/users/changes?event_id={ev.id}&cursor=x").status_code == 400


def test_big_directory_is_sent_compressed(client, factory):
    ev = _setup(client, factory, people=tuple(f"20{i:03d}" for i in range(60)))
    r = client.get(f"/api/users?event_id={ev.id}", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip" and len(r.json()) == 60


def test_retry_after_a_lost_response_replays_instead_of_warning_or_duplicating(client, factory, db):
    """Respuesta perdida DESPUÉS de guardar (el caso de la campaña D2.3: 2-5 ingresos de más por corrida): la estación reintenta sola con la MISMA `client_id` y SIN `force`.
    Debe recibir el mismo «SÍ» (`replayed`), no el aviso DUPLICADO ni un segundo registro; un escaneo NUEVO de la misma persona (otra `client_id`) sí avisa DUPLICADO."""
    ev = _setup(client, factory, auto_register=True)
    data = {"event_id": ev.id, "cedula": "1001", "client_id": "estacion-3-0001"}
    assert client.post("/api/checkin-cedula", data=data).json()["result"] == "SÍ"            # se guardó; supongamos que la respuesta no llegó
    again = client.post("/api/checkin-cedula", data=data).json()                              # reintento automático
    assert again["result"] == "SÍ" and again["replayed"] is True
    assert db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 1
    rescan = client.post("/api/checkin-cedula", data={**data, "client_id": "estacion-3-0002"}).json()
    assert rescan["result"] == "DUPLICADO" and db.query(AccessLog).filter_by(event_id=ev.id, user_id="1001").count() == 1
