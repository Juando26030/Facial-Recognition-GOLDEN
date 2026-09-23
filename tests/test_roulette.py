"""Ruleta: los 6 modos (5a y 5b por separado), filtros, auditoría, permisos y pantalla pública (Sprint 5)."""
from datetime import datetime

from tests.conftest import login


def _setup(client, factory, db, n=10, role="coordinador"):
    from app.models import EventAttendee, User

    staff = factory.staff(role, "coord1")
    ev = factory.event("en_proceso", coordinator=staff)
    cats = ["VIP", "General"]
    for i in range(1, n + 1):
        u = factory.person(ev, f"{1000 + i}", f"Nombre{i}", f"Apellido{i}")
        u.entity = "ACME" if i % 2 else "OTRA"
        u.set_extras({"opcional_1": "Talla M" if i <= 3 else "Talla L"})
        db.query(EventAttendee).filter_by(event_id=ev.id, user_id=u.id).update({"categories": '["VIP"]' if i <= 4 else '["General"]'})
    ev.categories = '["VIP","General"]'
    db.commit()
    login(client, "coord1")
    return ev


def _save(client, ev, **behavior):
    return client.put(f"/api/events/{ev.id}/roulette/behavior", json=behavior)


def _run(client, ev, label="Sorteo"):
    return client.post(f"/api/events/{ev.id}/roulette/execute", json={"label": label})


# ------------------------------- modos 1-3 (predeterminados a mano) -------------------------------
def test_mode1_single_fixed_reveals_exactly_the_chosen_winner(client, factory, db):
    ev = _setup(client, factory, db)
    assert _save(client, ev, mode="single_fixed", winners=["1003"]).status_code == 200
    r = _run(client, ev).json()
    assert [w["id"] for w in r["winners"]] == ["1003"] and r["is_random"] is False
    assert _save(client, ev, mode="single_fixed", winners=["1001", "1002"]).status_code == 400   # exactamente uno


def test_mode2_ordered_keeps_the_exact_order_every_time(client, factory, db):
    ev = _setup(client, factory, db)
    _save(client, ev, mode="ordered", winners=["1005", "1002", "1009"])
    for _ in range(3):
        assert [w["id"] for w in _run(client, ev).json()["winners"]] == ["1005", "1002", "1009"]


def test_mode3_shuffled_uses_the_same_set_in_varying_order(client, factory, db):
    ev = _setup(client, factory, db)
    chosen = ["1001", "1002", "1003", "1004", "1005", "1006"]
    _save(client, ev, mode="shuffled", winners=chosen)
    orders = {tuple(w["id"] for w in _run(client, ev).json()["winners"]) for _ in range(12)}
    assert all(sorted(o) == sorted(chosen) for o in orders)
    assert len(orders) > 1                                             # el orden cambia entre ejecuciones


def test_winners_must_belong_to_the_event_base(client, factory, db):
    ev = _setup(client, factory, db)
    r = _save(client, ev, mode="single_fixed", winners=["9999"])
    assert r.status_code == 400 and "9999" in r.json()["detail"]
    assert _save(client, ev, mode="ordered", winners=["1001"]).status_code == 400            # mínimo 2
    assert _save(client, ev, mode="ordered", winners=["1001", "1001"]).status_code == 400    # sin repetir


# ------------------------------- modo 4: todos -------------------------------
def test_mode4_all_draws_everyone_without_repeats_then_needs_a_new_round(client, factory, db):
    ev = _setup(client, factory, db, n=6)
    _save(client, ev, mode="all", batch_size=2)
    seen = []
    for _ in range(3):
        r = _run(client, ev).json()
        assert r["is_random"] is True and len(r["winners"]) == 2
        seen += [w["id"] for w in r["winners"]]
    assert sorted(seen) == [f"100{i}" for i in range(1, 7)]              # los 6, sin repetir
    end = _run(client, ev)
    assert end.status_code == 400 and "Reiniciar ronda" in end.json()["detail"]
    assert client.get(f"/api/events/{ev.id}/roulette/round").json() == {"drawn": 6, "total": 6}
    client.post(f"/api/events/{ev.id}/roulette/reset-round")
    assert _run(client, ev).status_code == 200                            # ronda nueva


# ------------------------------- modos 5a y 5b: dos flujos distintos -------------------------------
def test_mode5a_filter_only_narrows_the_list_and_the_operator_still_picks(client, factory, db):
    ev = _setup(client, factory, db)
    filt = {"conditions": [{"field": "category", "op": "equals", "value": "VIP"}]}
    listed = client.get(f"/api/events/{ev.id}/roulette/candidates", params={"filter": __import__("json").dumps(filt)}).json()
    assert listed["total"] == 4
    assert _save(client, ev, mode="filter_manual", winners=["1009"], filter=filt).status_code == 400   # 1009 no es VIP
    _save(client, ev, mode="filter_manual", winners=["1002"], filter=filt)
    r = _run(client, ev).json()
    assert [w["id"] for w in r["winners"]] == ["1002"] and r["is_random"] is False and len(r["pool"]) == 4


def test_mode5b_filter_random_is_a_real_draw_only_among_those_who_match(client, factory, db):
    ev = _setup(client, factory, db)
    filt = {"conditions": [{"field": "category", "op": "equals", "value": "VIP"}]}
    _save(client, ev, mode="filter_random", count=2, filter=filt, exclude_previous_winners=True)
    seen = set()
    for _ in range(2):
        r = _run(client, ev).json()
        assert r["is_random"] is True and len(r["winners"]) == 2
        seen |= {w["id"] for w in r["winners"]}
    assert seen == {"1001", "1002", "1003", "1004"}                       # solo VIP; sin repetir a los que ya ganaron
    assert _run(client, ev).status_code == 400                            # ya ganaron todos los VIP


def test_mode5b_can_repeat_winners_when_exclusion_is_off(client, factory, db):
    ev = _setup(client, factory, db)
    filt = {"conditions": [{"field": "entity", "op": "equals", "value": "acme"}]}
    _save(client, ev, mode="filter_random", count=5, filter=filt, exclude_previous_winners=False)
    assert _run(client, ev).status_code == 200 and _run(client, ev).status_code == 200


def test_filters_by_extra_field_registration_time_and_status(client, factory, db):
    from app.models import AccessLog

    ev = _setup(client, factory, db)
    for uid, hour in (("1001", 9), ("1002", 11), ("1003", 15)):                 # hora UTC; Bogotá = UTC-5
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Nuevo", timestamp=datetime(2026, 10, 1, hour, 0, 0)))
    db.commit()
    ask = lambda conds: client.get(f"/api/events/{ev.id}/roulette/candidates", params={"filter": __import__("json").dumps({"conditions": conds})}).json()["total"]
    assert ask([{"field": "extra:opcional_1", "op": "equals", "value": "talla m"}]) == 3
    assert ask([{"field": "status", "value": "registrado"}]) == 3
    assert ask([{"field": "status", "value": "no_registrado"}]) == 7
    # 09:00 UTC = 04:00 Bogotá; 11:00 UTC = 06:00; 15:00 UTC = 10:00
    assert ask([{"field": "registered_after", "value": "2026-10-01T05:00"}]) == 2
    assert ask([{"field": "registered_after", "value": "2026-10-01T05:00"}, {"field": "registered_before", "value": "2026-10-01T07:00"}]) == 1
    assert ask([{"field": "entity", "op": "contains", "value": "AC"}]) == 5
    assert client.get(f"/api/events/{ev.id}/roulette/candidates", params={"filter": '{"conditions":[{"field":"inventado","value":"x"}]}'}).status_code == 400


# ------------------------------- auditoría y reporte -------------------------------
def test_every_execution_is_recorded_and_exportable(client, factory, db, tmp_path):
    import openpyxl

    ev = _setup(client, factory, db)
    _save(client, ev, mode="ordered", winners=["1002", "1001"])
    _run(client, ev, label="Sorteo iPhone")
    _save(client, ev, mode="single_fixed", winners=["1004"])
    _run(client, ev, label="Sorteo bono")
    draws = client.get(f"/api/events/{ev.id}/roulette/draws").json()
    assert [d["label"] for d in draws] == ["Sorteo bono", "Sorteo iPhone"] and draws[1]["mode"] == "ordered"
    assert draws[1]["created_by"] and draws[1]["winners"][0]["id"] == "1002" and draws[0]["is_random"] is False
    rep = client.get(f"/api/events/{ev.id}/roulette/report")
    assert rep.status_code == 200
    path = tmp_path / "s.xlsx"
    path.write_bytes(rep.content)
    rows = list(openpyxl.load_workbook(path).active.iter_rows(values_only=True))
    body = [r for r in rows[2:] if r[0]]
    assert len(body) == 3 and body[0][2] == "Sorteo iPhone" and body[0][6] == "1002" and body[-1][6] == "1004"


# ------------------------------- permisos -------------------------------
def test_only_coordinador_plus_can_operate_the_roulette(client, factory, db):
    ev = _setup(client, factory, db)
    for role in ("digitador", "cliente"):
        client.post("/logout")
        s = factory.staff(role, f"u_{role}")
        factory.authorize(ev, s)
        login(client, s.username)
        assert client.get(f"/api/events/{ev.id}/roulette").status_code == 403, role
        assert client.post(f"/api/events/{ev.id}/roulette/execute", json={}).status_code == 403, role
        assert client.get(f"/kiosk/{ev.id}/ruleta").status_code in (302, 403), role
    client.post("/logout")
    factory.staff("comercial", "com1")
    login(client, "com1")
    assert client.get(f"/api/events/{ev.id}/roulette").status_code == 200        # comercial está sobre coordinador


def test_menu_shows_the_roulette_card_only_to_managers(client, factory, db):
    ev = _setup(client, factory, db)
    assert "Ruleta" in client.get(f"/kiosk/{ev.id}").text
    client.post("/logout")
    s = factory.staff("digitador", "9990001")
    factory.authorize(ev, s)
    login(client, "9990001")
    assert "🎡" not in client.get(f"/kiosk/{ev.id}").text


# ------------------------------- pantalla pública (proyector) -------------------------------
def test_display_page_needs_no_login_and_only_animates_new_draws(client, factory, db):
    ev = _setup(client, factory, db)
    url = client.post(f"/api/events/{ev.id}/roulette/display-link").json()["url"]
    token = url.rsplit("/r/", 1)[1]
    client.post("/logout")
    assert client.get(f"/r/{token}").status_code == 200
    assert client.get("/r/token-falso").status_code == 404
    base = client.get(f"/r/{token}/state").json()
    assert base["latest_id"] == 0 and base["draw"] is None and base["style"]["title"]
    client.post("/logout")
    login(client, "coord1")
    _save(client, ev, mode="single_fixed", winners=["1003"])
    _run(client, ev)
    client.post("/logout")
    assert client.get(f"/r/{token}/state").json()["draw"] is None                        # sin `after`: solo el id (liviano)
    first = client.get(f"/r/{token}/state", params={"after": 0}).json()
    assert first["draw"]["winners"][0]["id"] == "1003" and first["latest_id"] == 1
    assert client.get(f"/r/{token}/state", params={"after": 1}).json()["draw"] is None      # ya lo vio: no se repite
    assert client.get("/api/events/1/roulette").status_code == 401                           # y no abre nada más


def test_regenerating_the_display_link_kills_the_old_one(client, factory, db):
    ev = _setup(client, factory, db)
    old = client.post(f"/api/events/{ev.id}/roulette/display-link").json()["url"].rsplit("/r/", 1)[1]
    new = client.post(f"/api/events/{ev.id}/roulette/display-link", params={"regenerate": "true"}).json()["url"].rsplit("/r/", 1)[1]
    assert old != new and client.get(f"/r/{old}").status_code == 404 and client.get(f"/r/{new}").status_code == 200


# ------------------------------- estilo (pantalla visual) -------------------------------
def test_style_is_saved_separately_and_validated(client, factory, db):
    ev = _setup(client, factory, db)
    ok = client.put(f"/api/events/{ev.id}/roulette/style", json={"title": "Gran sorteo", "font_family": "Lobster", "colors": ["#FF0000", "#00FF00"], "background_color": "#101010", "spin_seconds": 9})
    assert ok.status_code == 200 and ok.json()["title"] == "Gran sorteo" and ok.json()["spin_seconds"] == 9
    assert client.put(f"/api/events/{ev.id}/roulette/style", json={"font_family": "Comic Inventada"}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/roulette/style", json={"colors": ["rojo", "azul"]}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/roulette/style", json={"background_color": "red"}).status_code == 400
    assert client.put(f"/api/events/{ev.id}/roulette/style", json={"background_image": "otro_cliente/x.png"}).status_code == 400
    cfg = client.get(f"/api/events/{ev.id}/roulette").json()
    assert cfg["style"]["font_family"] == "Lobster" and cfg["behavior"]["mode"] == "single_fixed"   # el comportamiento no se tocó


def test_execute_without_people_or_after_the_winner_left(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    assert _run(client, ev).status_code == 400 and "todavía no tiene personas" in _run(client, ev).json()["detail"]


def test_deleting_an_event_removes_its_roulette_data(client, factory, db):
    from app.models import RouletteConfig, RouletteDraw

    ev = _setup(client, factory, db)
    _save(client, ev, mode="single_fixed", winners=["1001"])
    _run(client, ev)
    client.post("/logout")
    factory.staff("admin", "root")
    login(client, "root")
    assert client.delete(f"/api/events/{ev.id}").status_code == 200
    assert db.query(RouletteDraw).count() == 0 and db.query(RouletteConfig).count() == 0
