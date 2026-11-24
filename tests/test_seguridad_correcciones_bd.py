"""Correcciones de seguridad del 22-nov-2026, con base (docs/revision_2026-11-22/12_seguridad_correcciones.md): servidor local con alcance por cliente (0163), subidas solo de asistentes
del evento, servidor vinculado por un coordinador, y «tomar» un trabajo de impresión por POST. Mismo estilo que tests/test_evento_compartido.py."""
from app import node_auth, versioning
from app.models import AuditConsentLog, EventAttendee, LocalNode, LocalServerKey, PersonChangeLog, User, WebAcceptance
from app.timeutil import utcnow
from tests.conftest import PASSWORD, login

HEAD = versioning.schema_head()
INST = "b" * 32


def _hdr(token):
    return {"X-Node-Token": token, "X-Node-Schema": HEAD, "X-Node-Version": f"abc|{HEAD}"}


def _node(db, staff, name, tenant_id=None):
    token, digest = node_auth.generate_token()
    db.add(LocalNode(name=name, token_hash=digest, created_by_id=staff.id, tenant_id=tenant_id))
    db.commit()
    return token


# ------------------------------------------------------------------ 1. alcance por cliente
def test_node_bound_to_a_tenant_only_reaches_its_events(client, factory, db):
    admin = factory.staff("admin", "adm_t")
    mine, other = factory.event("en_proceso", tenant_id="acme"), factory.event("en_proceso", tenant_id="otro")
    factory.person(other, "2002")
    bound, free = _node(db, admin, "Portátil Acme", "acme"), _node(db, admin, "Portátil libre")
    listed = {e["id"] for e in client.get("/api/node/events", headers=_hdr(bound)).json()["events"]}
    assert mine.id in listed and other.id not in listed
    assert {mine.id, other.id} <= {e["id"] for e in client.get("/api/node/events", headers=_hdr(free)).json()["events"]}          # sin cliente: como siempre
    assert client.post(f"/api/node/events/{other.id}/lease", headers=_hdr(bound)).status_code == 404
    db.expire_all()
    assert db.get(type(other), other.id).local_node_name is None                                   # no lo tomó: la nube sigue registrando
    for method, path in (("get", "package"), ("get", "inventory-checklist"), ("post", "abort"), ("get", "changes")):
        assert getattr(client, method)(f"/api/node/events/{other.id}/{path}", headers=_hdr(bound)).status_code == 404, path
    assert client.post(f"/api/node/events/{other.id}/precheck", json={}, headers=_hdr(bound)).status_code == 404
    assert client.post(f"/api/node/events/{mine.id}/lease", headers=_hdr(bound)).status_code == 200
    assert client.get(f"/api/node/events/{mine.id}/package", headers=_hdr(bound)).status_code == 200
    assert client.post(f"/api/node/events/{other.id}/lease", headers=_hdr(free)).status_code == 200  # el servidor sin cliente sigue pudiendo


def test_bound_node_cannot_upload_to_another_tenants_event_even_if_named_in_the_lease(client, factory, db):
    admin = factory.staff("admin", "adm_t2")
    other = factory.event("en_proceso", tenant_id="otro")
    bound = _node(db, admin, "Portátil Acme", "acme")
    other.local_node_name = "Portátil Acme"                                                         # arriendo viejo o puesto a mano desde la nube
    db.commit()
    for path, body in (("uploaded", None), ("release", {"pending": 0}), ("extra", {"edits": []}), ("records", {"print_logs": []})):
        assert client.post(f"/api/node/events/{other.id}/{path}", json=body or {}, headers=_hdr(bound)).status_code == 404, path


def test_key_tenant_is_optional_and_the_node_inherits_it(client, factory, db):
    factory.staff("admin", "adm_k")
    factory.tenant("acme")
    login(client, "adm_k")
    plain = client.post("/api/server-keys", json={"label": "Sin cliente"}).json()
    assert plain["tenant_id"] is None and plain["tenant_name"] is None                              # sin elegir: como hoy
    assert client.post("/api/server-keys", json={"label": "x", "tenant_id": "no-existe"}).status_code == 400
    k = client.post("/api/server-keys", json={"label": "Feria Acme", "tenant_id": "acme"}).json()
    assert k["tenant_id"] == "acme" and k["tenant_name"] == "ACME"
    rows = {r["code"]: r for r in client.get("/api/server-keys").json()["keys"]}
    assert rows[k["code"]]["tenant_name"] == "ACME" and rows[plain["code"]]["tenant_id"] is None
    client.get("/logout")
    assert client.post("/api/node/key/claim", json={"key": k["code"], "installation_id": INST}).status_code in (200, 503)
    key = db.query(LocalServerKey).filter_by(code=k["code"]).one()
    key.claimed_at, key.installation_id = utcnow(), INST                                             # por si el paquete no está publicado en la prueba (503)
    db.commit()
    r = client.post("/api/node/enroll", json={"username": "adm_k", "password": PASSWORD, "key": k["code"], "installation_id": INST})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(LocalNode).filter_by(name=r.json()["name"]).one().tenant_id == "acme"


# ------------------------------------------------------------------ 2. solo asistentes del evento
def test_uploads_only_touch_attendees_of_the_leased_event(client, factory, db):
    admin = factory.staff("admin", "adm_e")
    ev, elsewhere = factory.event("en_proceso"), factory.event("en_proceso")
    factory.person(ev, "1001")
    factory.person(elsewhere, "3003")                                                               # mismo cliente, OTRO evento
    token = _node(db, admin, "Puerta A")
    ev.local_node_name = "Puerta A"
    db.commit()
    t0 = utcnow().replace(microsecond=0).isoformat()
    body = {"edits": [{"cedula": "1001", "field": "email", "old": None, "new": "ana@x.co", "at": t0, "source": "edit"},
                      {"cedula": "3003", "field": "email", "old": None, "new": "malo@x.co", "at": t0, "source": "edit"}],
            "consents": [{"id": "6f1c2b9e-0000-4000-8000-0000000000a1", "cedula": "3003", "at": t0, "version": "v1", "legal_text_hash": "ab" * 32, "accepted": True, "adult": True, "reason": "consent"}]}
    out = client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(token)).json()
    assert out["ok"] is True and out["saved"]["edits"] == 1 and out["saved"]["consents"] == 0 and out["rejected"] == 2          # el ciclo NO se rompe: 200 y cuenta
    db.expire_all()
    assert db.query(User).filter_by(id="1001").one().email == "ana@x.co"
    assert db.query(User).filter_by(id="3003").one().email is None
    assert db.query(PersonChangeLog).filter_by(user_id="3003").count() == 0 and db.query(AuditConsentLog).filter_by(user_id="3003").count() == 0
    rec = {"person_changes": [{"cedula": "3003", "at": t0, "kind": "birth_date", "new_value": "2015-01-01"},
                              {"cedula": "1001", "at": t0, "kind": "birth_date", "new_value": "1990-05-05"}]}
    out = client.post(f"/api/node/events/{ev.id}/records", json=rec, headers=_hdr(token)).json()
    assert out["ok"] is True and out["rejected"] == 1
    db.expire_all()
    assert db.query(User).filter_by(id="3003").one().birth_date is None and db.query(User).filter_by(id="1001").one().birth_date is not None


def test_biometric_consent_from_a_node_is_recognized_without_verification(client, factory, db):
    from app import consent
    admin = factory.staff("admin", "adm_c")
    ev = factory.event("en_proceso")
    factory.person(ev, "1001")
    factory.person(ev, "1002")
    token = _node(db, admin, "Puerta A")
    ev.local_node_name = "Puerta A"
    db.commit()
    t0 = utcnow().replace(microsecond=0).isoformat()

    def row(n, uid):
        return {"id": f"6f1c2b9e-0000-4000-8000-00000000000{n}", "cedula": uid, "at": t0, "version": "v1", "legal_text_hash": "ab" * 32, "accepted": True, "adult": True, "reason": "consent"}

    body = {"consents": [row(1, "1001"), row(2, "1002")],
            "acceptances": [{"cedula": "1002", "created_at": t0, "verified_at": t0, "verified_via": "staff"}]}          # a 1002 la verificó el personal en el servidor local
    saved = client.post(f"/api/node/events/{ev.id}/extra", json=body, headers=_hdr(token)).json()["saved"]
    assert saved["consents"] == 2
    db.expire_all()
    assert consent.accepted_user_ids(db, ev.tenant_id, ev.id) == {"1001", "1002"}                   # 23-nov: ya no hay «por verificar»: las dos aceptaciones valen


# ------------------------------------------------------------------ 3. servidor vinculado por un coordinador
def test_node_linked_by_a_coordinator_can_upload(client, factory, db):
    coord = factory.staff("coordinador", "coord_n")
    ev = factory.event("en_proceso", coordinator=coord)
    factory.person(ev, "1001")
    token = _node(db, coord, "Puerta Coord")
    ev.local_node_name = "Puerta Coord"
    db.commit()
    t0 = utcnow().replace(microsecond=0).isoformat()
    r = client.post(f"/api/node/events/{ev.id}/access-logs", json={"records": [{"client_id": "n1-l1", "cedula": "1001", "timestamp": t0, "method": "cedula"}]}, headers=_hdr(token))
    assert r.status_code == 200, r.text                                                             # antes: 403 en cada ciclo y los ingresos se quedaban en el portátil
    assert client.post(f"/api/node/events/{ev.id}/records", json={"print_logs": [{"cedula": "1001", "printed_at": t0, "kind": "normal"}]}, headers=_hdr(token)).status_code == 200
    assert client.post(f"/api/node/events/{ev.id}/extra", json={"edits": []}, headers=_hdr(token)).status_code == 200


def test_node_linked_by_an_account_that_can_no_longer_link_is_refused(client, factory, db):
    dig = factory.staff("digitador", "dig_n")
    ev = factory.event("en_proceso")
    token = _node(db, dig, "Puerta Dig")
    ev.local_node_name = "Puerta Dig"
    db.commit()
    assert client.post(f"/api/node/events/{ev.id}/extra", json={"edits": []}, headers=_hdr(token)).status_code == 403


# ------------------------------------------------------------------ 5. print-jobs-next por POST (y GET durante la transición)
def test_print_jobs_next_answers_post_like_get(client, factory, db):
    factory.staff("coordinador", "coord_p")
    ev = factory.event("en_proceso")
    login(client, "coord_p")
    get, post = client.get(f"/api/events/{ev.id}/print-jobs-next"), client.post(f"/api/events/{ev.id}/print-jobs-next")
    assert post.status_code == get.status_code                                                      # misma puerta (impresión compartida encendida o no)
    if get.status_code == 200:
        assert post.json() == get.json()
    assert db.query(EventAttendee).count() == 0
