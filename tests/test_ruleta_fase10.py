"""Ruleta, Fase 10 (bloque C): datos del ganador a elegir, logos/banners de arriba y giro libre (clic para iniciar, clic para detener). Todo vive en style_json: sin migración."""
import json
import pathlib
import shutil
import subprocess

import pytest

from tests.conftest import login

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _setup(client, factory, db):
    staff = factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso", coordinator=staff)
    ev.set_optional_labels({"opcional_1": "Ciudad", "opcional_2": "Talla"})
    for i in range(1, 4):
        u = factory.person(ev, f"{1000 + i}", f"Nombre{i}", f"Apellido{i}")
        u.entity, u.email, u.role = "ACME", f"p{i}@ejemplo.co", "Gerente"
        u.set_extras({"opcional_1": "Medellín", "opcional_2": "M"})
    db.commit()
    login(client, "coord1")
    return ev


def _style(client, ev, **data):
    return client.put(f"/api/events/{ev.id}/roulette/style", json=data)


def _run(client, ev, winner="1002"):
    assert client.put(f"/api/events/{ev.id}/roulette/behavior", json={"mode": "single_fixed", "winners": [winner]}).status_code == 200
    return client.post(f"/api/events/{ev.id}/roulette/execute", json={"label": "S"}).json()


def test_defaults_keep_the_old_behaviour(client, factory, db):
    ev = _setup(client, factory, db)
    cfg = client.get(f"/api/events/{ev.id}/roulette").json()
    assert cfg["style"]["winner_fields"] == ["entity"] and cfg["style"]["top_images"] == [] and cfg["style"]["spin_mode"] == "fixed"
    keys = [c["key"] for c in cfg["winner_field_choices"]]
    assert keys == ["entity", "email", "role", "opt_1", "extra:opcional_1", "extra:opcional_2"]
    assert [c["label"] for c in cfg["winner_field_choices"]][-2:] == ["Ciudad", "Talla"]        # los campos del evento salen con su nombre


def test_winner_fields_are_validated_and_drive_what_the_winner_card_carries(client, factory, db):
    ev = _setup(client, factory, db)
    assert _style(client, ev, winner_fields=["entity", "cedula"]).status_code == 400            # un dato que no se ofrece
    assert _style(client, ev, winner_fields=["extra:opcional_9"]).status_code == 400            # campo que el evento no tiene
    assert _style(client, ev, winner_fields="entity").status_code == 400
    assert _style(client, ev, winner_fields=["entity", "email", "extra:opcional_1", "entity"]).json()["winner_fields"] == ["entity", "email", "extra:opcional_1"]
    res = _run(client, ev)
    assert res["winners"][0]["fields"] == [
        {"key": "entity", "label": "Empresa", "value": "ACME"}, {"key": "email", "label": "Correo", "value": "p2@ejemplo.co"}, {"key": "extra:opcional_1", "label": "Ciudad", "value": "Medellín"}]
    _style(client, ev, winner_fields=[])                                                         # solo el nombre
    assert _run(client, ev)["winners"][0]["fields"] == []


def test_public_screen_gets_only_the_chosen_fields_and_never_the_cedula(client, factory, db):
    ev = _setup(client, factory, db)
    _style(client, ev, winner_fields=["email"])
    token = client.post(f"/api/events/{ev.id}/roulette/display-link").json()["url"].rsplit("/r/", 1)[1]
    _run(client, ev)
    client.post("/logout")
    w = client.get(f"/r/{token}/state", params={"after": 0}).json()["draw"]["winners"][0]
    assert w["fields"] == [{"label": "Correo", "value": "p2@ejemplo.co", "entity": False}] and "entity" not in w and "id" not in w
    assert "ACME" not in json.dumps(w) and "1002" not in json.dumps(w)                         # desmarcó la empresa: ni siquiera viaja


def test_old_draws_without_fields_still_show_the_entity(client, factory, db):
    from app.routers import roulette
    pub = roulette.public_winners([{"position": 1, "id": "1", "name": "Ana", "entity": "ACME"}])
    assert pub == [{"position": 1, "name": "Ana", "entity": "ACME"}]


def test_top_images_and_spin_mode(client, factory, db):
    ev = _setup(client, factory, db)
    own = f"{ev.tenant_id}/a.png"
    ok = _style(client, ev, top_images=[own, f"{ev.tenant_id}/b.jpg"], spin_mode="manual")
    assert ok.status_code == 200 and ok.json()["top_images"] == [own, f"{ev.tenant_id}/b.jpg"] and ok.json()["spin_mode"] == "manual"
    assert _style(client, ev, top_images=["otro-cliente/a.png"]).status_code == 400              # de otro cliente
    assert _style(client, ev, top_images=[f"{ev.tenant_id}/../x.png"]).status_code == 400
    assert _style(client, ev, top_images=[f"{ev.tenant_id}/x.exe"]).status_code == 400
    assert _style(client, ev, top_images=[f"{ev.tenant_id}/{i}.png" for i in range(5)]).status_code == 400   # máximo 4
    assert _style(client, ev, spin_mode="rapido").status_code == 400
    assert _style(client, ev, spin_mode="fixed").json()["spin_mode"] == "fixed"
    token = client.post(f"/api/events/{ev.id}/roulette/display-link").json()["url"].rsplit("/r/", 1)[1]
    client.post("/logout")
    assert client.get(f"/r/{token}/state").json()["style"]["top_images"] == [own, f"{ev.tenant_id}/b.jpg"]


# ------------------------------------------------------------------ texto de las pantallas (corre sin base)
def test_display_screen_has_the_free_spin_flow():
    page = (ROOT / "templates/roulette_display.html").read_text(encoding="utf-8")
    assert 'id="topImages"' in page and "RouletteRender.topImages" in page
    assert "spin_mode === 'manual'" in page and "{ stop }" in page and "if (freeStop) { freeStop(); return; }" in page and "'Detener'" in page
    assert "run(draw, manual())" in page and "run(st.draw)" in page                                  # el giro de otra pantalla no pide «Detener»
    js = (ROOT / "static/js/roulette-render.js").read_text(encoding="utf-8")
    assert "MAX_FREE_MS = 120000" in js and js.count("spinFree") >= 6 and "ctl.stop" in js


def test_appearance_screen_offers_the_new_options_and_stays_inside_the_design_system():
    page = (ROOT / "templates/kiosk_ruleta_visual.html").read_text(encoding="utf-8")
    for needle in ('id="spin_mode"', 'id="winnerFields"', 'id="topFile"', "winner_field_choices", "style.top_images", "style.winner_fields", "previewStop"):
        assert needle in page, needle
    assert " onclick=" not in page and "alert(" not in page


def test_no_migration_was_needed():
    assert not list((ROOT / "alembic/versions").glob("*ruleta_cfg*"))


# ------------------------------------------------------------------ JS en Node
def test_roulette_render_pure_parts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no está instalado")
    expr = ("const R=require('./static/js/roulette-render.js');console.log(JSON.stringify([R.fieldRows({name:'A',entity:'E'}),R.fieldRows({name:'A',entity:'E',fields:[]}),"
            "R.fieldRows({name:'A',fields:[{label:'Correo',value:'a@b.co'},{label:'X',value:''}]})]))")
    out = json.loads(subprocess.run([node, "-e", expr], capture_output=True, text=True, cwd=ROOT, check=True).stdout)
    assert out == [[{"label": "", "value": "E", "entity": True}], [], [{"label": "Correo", "value": "a@b.co", "entity": False}]]


def test_logo_sizes_and_text_scales(client, factory, db):
    ev = _setup(client, factory, db)
    cfg = client.get(f"/api/events/{ev.id}/roulette").json()["style"]
    assert cfg["fields_scale"] > cfg["name_scale"] and cfg["top_images_cfg"] == []        # los demás datos salen más grandes que antes
    bad = _style(client, ev, name_scale="mucho")
    assert bad.status_code == 400
    r = _style(client, ev, name_scale=900, fields_scale=10)
    assert r.status_code == 200 and r.json()["name_scale"] == 400 and r.json()["fields_scale"] == 50
    r = _style(client, ev, top_images=["acme/a.png", "acme/b.png"], top_images_cfg=[{"height": 99, "align": "right"}, {"height": "x", "align": "zzz"}])
    assert r.status_code == 200
    assert r.json()["top_images_cfg"] == [{"height": 40, "align": "right"}, {"height": 18, "align": "center"}]
    r = _style(client, ev, top_images_cfg=[{"height": 25, "align": "left"}])        # solo tamaño: se ajusta al número de imágenes
    assert [c["height"] for c in r.json()["top_images_cfg"]] == [25, 18]


def test_logo_size_and_text_scale_controls_are_in_the_screens():
    root = pathlib.Path(__file__).resolve().parent.parent
    vis = (root / "templates/kiosk_ruleta_visual.html").read_text(encoding="utf-8")
    assert "fields_scale" in vis and "name_scale" in vis and "data-top-h" in vis and "data-top-a" in vis
    css = (root / "static/css/gw-ruleta-display.css").read_text(encoding="utf-8")
    assert "--rr-fields-scale" in css and "--rr-top-h" in css
    assert "--rr-top-h" in (root / "static/js/roulette-render.js").read_text(encoding="utf-8")
