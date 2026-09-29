"""Verificación del operador tras un escaneo facial (docs/14 §6.3): candidatos del MISMO cálculo, foto de registro, confianza en palabras, regla DUDOSO
(MATCH_MARGIN), permisos de las fotos y «confirmar a otra persona». El motor dlib se reemplaza por un doble; las distancias se controlan poniendo cada
persona a una distancia exacta del encoding «visto» (el vector cero)."""
import io
import json

import pytest
from PIL import Image

from app import faces
from app.models import AccessLog, StaffUser
from app.storage import get_storage, photo_key
from tests.conftest import login


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


def _at(distance: float, axis: int) -> str:
    v = [0.0] * 128
    v[axis] = distance
    return json.dumps(v)


@pytest.fixture()
def scan(monkeypatch):
    from app.biometrics import BiometricEngine
    state = type("S", (), {"calls": 0})()

    def fake_extract(img, is_registration=False, **kw):
        state.calls += 1
        return [0.0] * 128                                  # el rostro «visto» es el vector cero

    monkeypatch.setattr(BiometricEngine, "extract_encoding", staticmethod(fake_extract))
    return state


def _setup(client, factory, db, distances, **event_kw):
    """Evento en proceso con una persona por distancia (cédulas 100100, 100101…, nombres «Persona N») y un digitador autorizado con sesión iniciada."""
    from app.models import EventAttendee, User
    op = factory.staff("digitador", "9990001")
    ev = factory.event("en_proceso", facial_enabled=True, **event_kw)
    factory.authorize(ev, op)
    for i, d in enumerate(distances):
        uid = str(100100 + i)
        db.add(User(id=uid, tenant_id=ev.tenant_id, first_name=f"Persona{i + 1}", last_name="Prueba", face_encoding=_at(d, i)))
        db.flush()
        db.add(EventAttendee(event_id=ev.id, user_id=uid, tenant_id=ev.tenant_id))
        get_storage().put(photo_key(ev.tenant_id, uid), b"JPEGDATA-" + uid.encode())
    db.commit()
    login(client, "9990001")
    return ev


def _scan(client, ev, **extra):
    return client.post("/api/recognize", data={"event_id": ev.id, **extra}, files={"file": ("s.png", _png(), "image/png")})


def _tok(client, ev, token, url, **extra):
    return client.post(url, data={"event_id": ev.id, "match_token": token, **extra})


# ------------------------------------------------------------------ candidatos y confianza
def test_match_carries_photo_ready_info_and_the_five_next_candidates_come_from_the_same_calculation(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.30, 0.52, 0.58, 0.70, 0.80, 0.90, 1.0])            # 7 personas: principal + 5 siguientes (la 7.ª ni se ofrece)
    r = _scan(client, ev)
    body = r.json()
    assert r.headers["cache-control"] == "private, no-store"
    assert body["result"] == "MATCH_PENDING" and body["data"]["id"] == "100100" and body["has_candidates"] is True
    assert body["match"]["confidence"] == {"level": "high", "label": "Muy parecido"} and body["match"]["id"] == "100100"          # la principal, con su cédula
    cands = _tok(client, ev, body["match_token"], "/api/recognize/candidates").json()["candidates"]
    assert [c["index"] for c in cands] == [1, 2, 3, 4, 5]
    assert [c["id"] for c in cands] == ["***0101", "***0102", "***0103", "***0104", "***0105"]                                   # cédula parcial
    assert [c["within_tolerance"] for c in cands] == [True, False, False, False, False]                                          # 0,52 sí; el resto fuera de 0,55
    assert cands[0]["confidence"]["label"] == "Revisar con cuidado" and cands[1]["confidence"]["level"] == "out"
    assert scan.calls == 1                                                                                                       # ni el rostro ni la foto se procesaron de nuevo


def test_confidence_words_and_doubt_rule():
    assert [faces.confidence(d)["level"] for d in (0.10, 0.45, 0.54, 0.55, 0.9)] == ["high", "medium", "low", "out", "out"]
    assert faces.is_doubtful([("a", 0.30), ("b", 0.35)]) and not faces.is_doubtful([("a", 0.30), ("b", 0.37)]) and not faces.is_doubtful([("a", 0.30)])


def test_top_returns_sorted_candidates_even_with_fewer_people_than_k():
    import numpy as np
    idx = faces._Index(1, ["a", "b", "c"], np.array([[3.0, 0], [1.0, 0], [2.0, 0]], dtype=np.float32))
    assert [u for u, _ in idx.top([0, 0], k=6)] == ["b", "c", "a"] and idx.top([0, 0], k=1)[0][0] == "b"


# ------------------------------------------------------------------ DUDOSO
def test_doubtful_match_shows_candidates_and_is_never_registered_even_with_auto_register(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.40, 0.43, 0.90], auto_register=True)                # diferencia 0,03 < 0,06
    body = _scan(client, ev).json()
    assert body["result"] == "DUDOSO" and [c["index"] for c in body["candidates"]] == [0, 1, 2] and "data" not in body
    assert db.query(AccessLog).count() == 0                                                  # el autoregistro NO registra un caso dudoso
    again = _scan(client, ev, confirm="true", force="true").json()
    assert again["result"] == "DUDOSO" and db.query(AccessLog).count() == 0                  # ni forzando ni confirmando
    with_token = client.post("/api/recognize", data={"event_id": ev.id, "match_token": body["match_token"], "confirm": "true"}).json()
    assert with_token["result"] == "DUDOSO" and db.query(AccessLog).count() == 0             # ni con el token del propio escaneo


def test_clear_winner_registers_with_auto_register_and_margin_is_configurable(client, factory, db, scan, monkeypatch):
    ev = _setup(client, factory, db, [0.40, 0.50, 0.90], auto_register=True)                # diferencia 0,10 ≥ 0,06
    assert _scan(client, ev).json()["result"] == "SÍ" and db.query(AccessLog).filter_by(user_id="100100", registration_method="biometrico").count() == 1
    db.query(AccessLog).delete()
    db.commit()
    monkeypatch.setattr(faces, "MATCH_MARGIN", 0.20)                                          # con un margen mayor, la misma foto pasa a dudosa
    assert _scan(client, ev, force="true").json()["result"] == "DUDOSO"


# ------------------------------------------------------------------ fotos y permisos
def test_candidate_photos_are_private_limited_to_the_token_and_never_in_the_url(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.30, 0.52, 0.58])
    token = _scan(client, ev).json()["match_token"]
    photo = _tok(client, ev, token, "/api/recognize/photo", index=1)
    assert photo.status_code == 200 and photo.content == b"JPEGDATA-100101" and photo.headers["cache-control"] == "private, no-store"
    assert _tok(client, ev, token, "/api/recognize/photo", index=0).content == b"JPEGDATA-100100"
    assert _tok(client, ev, token, "/api/recognize/photo", index=3).status_code == 404       # fuera del token: no se puede pedir la foto de cualquiera
    assert _tok(client, ev, token, "/api/recognize/photo", index=-1).status_code == 404
    get_storage().delete(photo_key(ev.tenant_id, "100102"))
    assert _tok(client, ev, token, "/api/recognize/photo", index=2).status_code == 404       # sin foto de registro
    assert client.get("/api/recognize/photo", params={"event_id": ev.id}).status_code == 405  # solo POST: la cédula/token nunca van en una URL (ni en los logs)


def test_photos_need_an_authorized_operator_the_same_event_and_a_live_token(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.30, 0.52])
    token = _scan(client, ev).json()["match_token"]
    other_event = factory.event("en_proceso", facial_enabled=True)
    factory.authorize(other_event, db.query(StaffUser).filter_by(username="9990001").one())
    assert _tok(client, other_event, token, "/api/recognize/photo", index=0).status_code == 400          # el token es de OTRO evento
    assert _tok(client, ev, "token-falso", "/api/recognize/photo", index=0).status_code == 400
    client.post("/logout")
    factory.staff("digitador", "9990002")                                                                # digitador sin autorización en el evento
    login(client, "9990002")
    assert _tok(client, ev, token, "/api/recognize/photo", index=0).status_code in (400, 403)            # ni con la foto ni con el token de otro operador
    assert _tok(client, ev, token, "/api/recognize/candidates").status_code in (400, 403)
    client.post("/logout")
    factory.staff("cliente", "cli1", tenant_id=ev.tenant_id)
    login(client, "cli1")
    assert _tok(client, ev, token, "/api/recognize/photo", index=0).status_code == 403                   # el rol cliente no verifica escaneos
    client.post("/logout")
    assert _tok(client, ev, token, "/api/recognize/photo", index=0).status_code in (401, 403)            # sin sesión


def test_expired_token_asks_to_scan_again(client, factory, db, scan, monkeypatch):
    ev = _setup(client, factory, db, [0.30, 0.52])
    token = _scan(client, ev).json()["match_token"]
    monkeypatch.setattr(faces, "MATCH_TOKEN_TTL", -1)
    r = _tok(client, ev, token, "/api/recognize/candidates")
    assert r.status_code == 400 and "venció" in r.json()["detail"]


# ------------------------------------------------------------------ confirmar a OTRA persona
def test_confirming_from_a_candidate_registers_that_person_and_not_the_best_match(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.40, 0.43, 0.90])
    body = _scan(client, ev).json()                                                                      # dudoso: 100100 y 100101 casi empatadas
    row = _tok(client, ev, body["match_token"], "/api/recognize/person", index=1).json()                 # el operador compara y elige a la 2.ª
    assert row["id"] == "100101" and row["status"] == "No registrado" and "extra_fields" in row
    r = client.patch(f"/api/events/{ev.id}/users/{row['id']}/status", json={"status": "registrado", "method": "biometrico"})
    assert r.status_code == 200
    logs = db.query(AccessLog).filter_by(event_id=ev.id).all()
    assert [(log.user_id, log.registration_method) for log in logs] == [("100101", "biometrico")]          # se registró la elegida; la mejor coincidencia no
    assert scan.calls == 1
    assert _tok(client, ev, body["match_token"], "/api/recognize/person", index=9).status_code == 404


def test_manual_status_change_keeps_the_traditional_method_by_default(client, factory, db, scan):
    ev = _setup(client, factory, db, [0.30])
    assert client.patch(f"/api/events/{ev.id}/users/100100/status", json={"status": "registrado"}).status_code == 200
    assert db.query(AccessLog).one().registration_method == "tradicional"


# ------------------------------------------------------------------ pantalla
def test_scanner_page_has_the_result_panel_and_the_autoregister_warning(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", facial_enabled=True)
    login(client, "coord1")
    page = client.get(f"/kiosk/{ev.id}/registro").text
    assert 'id="scanResult"' in page and 'id="scanMoreBtn"' in page and "Ver 5 más cercanos" in page
    assert 'id="autoRegisterWarn"' in page and "no se recomienda en eventos grandes" in page
    plain = factory.event("en_proceso", facial_enabled=False)
    assert 'id="autoRegisterWarn"' not in client.get(f"/kiosk/{plain.id}/registro").text                 # sin rostro no hay advertencia


def test_top_counts_each_person_once_so_a_second_encoding_never_makes_it_doubtful():
    """Personas con 2 encodings: el «segundo» candidato de la regla DUDOSO es siempre OTRA persona, nunca la segunda foto de la misma."""
    import numpy as np
    rows = np.array([[0.30, 0], [0.32, 0], [0.40, 0], [0.90, 0]], dtype=np.float32)
    idx = faces._Index(1, ["A", "A", "B", "C"], rows)                        # A tiene 2 encodings (0,30 y 0,32); B está a 0,40
    ranked = idx.top([0, 0])
    assert [u for u, _ in ranked] == ["A", "B", "C"]                          # A aparece UNA vez
    assert not faces.is_doubtful(ranked)                                      # 0,40 − 0,30 = 0,10 ≥ 0,06; contra su propia 2.ª foto (0,02) habría dado DUDOSO
    close = faces._Index(1, ["A", "A", "B"], np.array([[0.30, 0], [0.31, 0], [0.34, 0]], dtype=np.float32)).top([0, 0])
    assert faces.is_doubtful(close) and [u for u, _ in close] == ["A", "B"]   # y sí es dudoso cuando OTRA persona queda a menos de 0,06


def test_one_encoding_per_person_ranks_exactly_like_the_previous_argpartition_version():
    """El caso de hoy (un encoding por persona) no cambia: mismo orden y mismas distancias que la versión anterior de `top` (argpartition + argsort)."""
    import numpy as np
    rng = np.random.default_rng(7)
    for n, k in ((1, 6), (3, 6), (6, 6), (50, 6), (500, 6), (500, 3)):
        matrix = rng.normal(0, 0.1, (n, 128)).astype(np.float32)
        ids = [f"p{i}" for i in range(n)]
        vec = rng.normal(0, 0.1, 128).astype(np.float32)
        dist = np.linalg.norm(matrix - vec, axis=1)
        kk = min(k, n)
        part = np.argpartition(dist, kk - 1)[:kk]
        old = [(ids[int(i)], float(dist[int(i)])) for i in part[np.argsort(dist[part])]]
        assert faces._Index(1, ids, matrix).top(vec, k) == old


def test_recognize_with_two_encodings_per_person_is_not_doubtful_against_itself(client, factory, db, scan):
    from app.models import User
    ev = _setup(client, factory, db, [0.40, 0.90])
    u = db.query(User).filter_by(id="100100").one()
    u.face_encoding = json.dumps([json.loads(_at(0.40, 0)), json.loads(_at(0.41, 5))])      # 2.º encoding de la MISMA persona, casi idéntico
    db.commit()
    faces.clear_cache()
    body = _scan(client, ev).json()
    assert body["result"] == "MATCH_PENDING" and body["data"]["id"] == "100100"
    cands = _tok(client, ev, body["match_token"], "/api/recognize/candidates").json()["candidates"]
    assert [c["id"] for c in cands] == ["***0101"]                                          # la lista no repite a la persona principal


def test_verification_js_uses_own_dialogs_and_lazy_photos():
    js = open("static/js/app.js", encoding="utf8").read()
    assert "alert(" not in js and "confirm(" not in js.replace("showConfirm(", "").replace("confirmDuplicateRegistration(", "")
    assert js.index("/api/recognize/candidates") < js.index("renderCandidates(data.candidates)")          # las fotos de los candidatos se piden al mostrar la lista
