"""Fase 3, commit 1: roster local del quiosco (`GET /api/events/{id}/local-roster`): contenido mínimo (sin fotos, encodings, teléfono ni correo), permisos por evento, límite de tasa,
ETag, evento finalizado y un evento de ~8.000 personas (tamaño y tiempo)."""
import gzip
import hashlib
import json
import time

from sqlalchemy import event

from app.database import engine
from app.models import AccessLog, EventAttendee, User
from app.routers import api
from tests.conftest import login


def _get(client, ev, **kw):
    return client.get(f"/api/events/{ev.id}/local-roster", **kw)


def _fp(salt, cedula):
    return hashlib.sha256(f"{salt}:{cedula}".encode()).hexdigest()[:16]


def test_roster_has_only_the_minimum_and_a_salted_fingerprint(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    u = factory.person(ev, "1001.234", "Ana", "Prueba")
    u.phone, u.email, u.opt_1, u.face_encoding = "3001112233", "ana@example.com", "VIP", json.dumps([0.1] * 128)
    db.commit()
    att = db.query(EventAttendee).filter_by(event_id=ev.id, user_id=u.id).one()
    att.set_categories(["Prensa", "Staff"])
    factory.person(ev, "2002", "Luis", "Gómez")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="2002", event_id=ev.id, record_type="Existente"))
    db.commit()
    login(client, "root")
    r = _get(client, ev)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"v", "generated_at", "max_age_s", "event", "salt", "count", "people", "consent"} and body["consent"] is None and body["count"] == 2 and body["max_age_s"] == 86400
    assert body["event"] == {"id": ev.id, "status": "en_proceso", "auto_register": False}
    by_name = {p["n"]: p for p in body["people"]}
    ana, luis = by_name["Ana Prueba"], by_name["Luis Gómez"]
    assert set(ana) == {"h", "n", "c", "s", "a", "b", "v"} and ana["a"] == 0 and ana["b"] == 0 and ana["v"] == 0                                              # nada más: ni cédula, ni teléfono, ni correo, ni encoding
    assert ana["h"] == _fp(body["salt"], "1001234")                                      # normalizada: sin puntos ni espacios (igual que el cliente)
    assert ana["c"] == ["Prensa", "Staff"] and ana["s"] == "No registrado" and luis["s"] == "Registrado"
    # La versión, la sal y las huellas son hex aleatorio: a veces contienen «2002» o «1001» por casualidad (falló el CI el 1-nov-2026). Se revisa todo lo demás.
    visible = json.dumps({**body, "v": "", "salt": "", "people": [{k: val for k, val in p.items() if k != "h"} for p in body["people"]]}, ensure_ascii=False)
    for secret in ("1001", "2002", "3001112233", "ana@example.com", "VIP", "0.1"):
        assert secret not in visible, secret
    other = factory.event("en_proceso")
    login(client, "root")
    assert _get(client, other).json()["salt"] != body["salt"]                            # sal distinta por evento
    assert _get(client, ev).json()["salt"] == body["salt"]                               # y estable


def test_roster_permissions_per_event(client, factory):
    factory.staff("admin", "root")
    dig_ok, cli = factory.staff("digitador", "dig_ok"), factory.staff("cliente", "cli")
    factory.staff("digitador", "dig_other")
    ev = factory.event("en_proceso")
    factory.authorize(ev, dig_ok)
    factory.authorize(ev, cli)
    assert _get(client, ev).status_code in (401, 403)                                    # sin sesión
    login(client, "dig_other")
    assert _get(client, ev).status_code == 403                                           # digitador sin autorización para ESTE evento
    login(client, "cli")
    assert _get(client, ev).status_code == 403                                           # el cliente puede ver, no acreditar: tampoco descarga el roster
    login(client, "dig_ok")
    assert _get(client, ev).status_code == 200


def test_roster_is_refused_for_a_finished_event(client, factory):
    factory.staff("admin", "root")
    ev = factory.event("finalizado")
    login(client, "root")
    assert _get(client, ev).status_code == 409


def test_roster_etag_returns_304_and_changes_with_the_directory(client, factory, db):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "root")
    first = _get(client, ev)
    etag = first.headers["etag"]
    assert _get(client, ev, headers={"If-None-Match": etag}).status_code == 304
    factory.person(ev, "1002")
    again = _get(client, ev, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.json()["count"] == 2 and again.headers["etag"] != etag


def test_roster_download_is_rate_limited_per_user_and_event(client, factory, monkeypatch):
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    login(client, "root")
    monkeypatch.setattr(api, "ROSTER_LIMIT", 3)
    assert [_get(client, ev).status_code for _ in range(3)] == [200, 200, 200]
    assert _get(client, ev).status_code == 429
    other = factory.event("en_proceso")
    login(client, "root")
    assert _get(client, other).status_code == 200                                        # el límite es por evento


def _seed_people(db, ev, n, first_id):
    users = [User(id=f"{first_id + i}", tenant_id=ev.tenant_id, first_name=f"Nombre{i}", last_name=f"Apellido{i}", phone="3001234567", email=f"p{i}@example.com", entity="Entidad de prueba S.A.S.")
             for i in range(n)]
    db.bulk_save_objects(users)
    db.commit()
    db.bulk_save_objects([EventAttendee(event_id=ev.id, user_id=u.id, tenant_id=ev.tenant_id, categories=json.dumps(["General"])) for u in users])
    db.add_all([AccessLog(tenant_id=ev.tenant_id, user_id=users[i].id, event_id=ev.id, record_type="Existente") for i in range(0, n, 4)])
    db.commit()
    return users


def _run_counting_queries(fn):
    """Ejecuta `fn()` y devuelve (resultado, sentencias SQL que se enviaron a la base)."""
    sent = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        sent.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        return fn(), sent
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def test_roster_of_8000_people_is_small_correct_and_needs_a_constant_number_of_queries(client, factory, db, monkeypatch):
    """Tamaño, correctitud y NÚMERO DE CONSULTAS (constante, no depende de cuántas personas haya); el tiempo solo se imprime. Antes afirmaba «< 5 s», que en el runner de GitHub dio 6,55 s
    (151 ms en local): el tiempo de un runner compartido no es una propiedad del código. Lo que sí es del código: 11 consultas con 100 personas y con 8.000, y un 304 que NO arma el
    roster (no calcula una sola huella)."""
    factory.staff("admin", "root")
    small, big = factory.event("en_proceso"), factory.event("en_proceso")
    n_small, n_big = 100, 8000
    _seed_people(db, small, n_small, 2000000000)
    users = _seed_people(db, big, n_big, 1000000000)
    login(client, "root")

    r_small, q_small = _run_counting_queries(lambda: _get(client, small))
    t = time.perf_counter()
    r_big, q_big = _run_counting_queries(lambda: _get(client, big))
    elapsed = time.perf_counter() - t
    assert r_small.status_code == 200 and r_big.status_code == 200
    assert len(q_small) == len(q_big) <= 15                                             # constante: no hay una consulta por persona (ni por categoría, ni por registro)

    body = r_big.json()
    raw, zipped = len(r_big.content), len(gzip.compress(r_big.content))
    registered = sum(p["s"] == "Registrado" for p in body["people"])
    print(f"roster {n_big}: {len(q_big)} consultas, {raw / 1024:.0f} KB sin comprimir, {zipped / 1024:.0f} KB gzip, {elapsed * 1000:.0f} ms (solo informativo)")
    assert body["count"] == n_big == len(body["people"]) and registered == n_big // 4
    assert len({p["h"] for p in body["people"]}) == n_big                               # sin colisiones de huella
    assert body["people"][0]["h"] == _fp(body["salt"], users[0].id) and body["people"][0]["n"] == "Nombre0 Apellido0"          # ordenado por cédula y bien calculado
    assert raw / n_big <= 120 and zipped / n_big <= 40                                  # tamaño por persona acotado (hoy ~88 B y ~17 B)
    assert elapsed < 30                                                                 # margen enorme: solo atrapa un bucle o una consulta fuera de control, no el ruido de un runner

    def boom(*a, **k):
        raise AssertionError("el 304 no debe armar el roster (ni una huella por persona)")

    monkeypatch.setattr(api, "roster_fingerprint", boom)
    r304, q304 = _run_counting_queries(lambda: _get(client, big, headers={"If-None-Match": r_big.headers["etag"]}))
    assert r304.status_code == 304 and not r304.content
    assert len(q304) < len(q_big)                                                       # menos consultas que el 200…
    assert not [q for q in q304 if "users.first_name" in q or "FILTER (WHERE" in q]     # …y ninguna de las dos que arman las 8.000 filas (personas y conteos por persona)
    print(f"roster {n_big}, 304: {len(q304)} consultas")
