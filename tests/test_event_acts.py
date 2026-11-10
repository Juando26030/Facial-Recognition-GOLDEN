"""Acta de novedades (Fase 10, 0126): lógica pura (corre sin base) y flujo completo con base (Cloud Shell)."""
import base64
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app import event_acts

ROOT = Path(__file__).resolve().parent.parent


def _png(blank=False) -> str:
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    if not blank:
        d = ImageDraw.Draw(img)
        d.line([(10, 100), (80, 20), (150, 100), (240, 30), (290, 90)], fill=(0, 0, 0, 255), width=5)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------------------------ puras
def test_clean_fields_text_and_list():
    f = event_acts.clean_fields({"title": "  Novedades   día 1 ", "body": "Hola\r\nmundo"})
    assert f == {"title": "Novedades día 1", "format": "text", "body": "Hola\nmundo"}
    f = event_acts.clean_fields({"title": "T", "format": "list", "body": "- uno\n\n• dos\n  tres"})
    assert f["body"] == "uno\ndos\ntres"


@pytest.mark.parametrize("data", [{"title": "", "body": "x"}, {"title": "t", "body": "  "}, {"title": "t", "body": "x", "format": "otro"}, {"title": "t" * 161, "body": "x"}, {"title": "t", "body": "x" * 10001}])
def test_clean_fields_rejects(data):
    with pytest.raises(ValueError):
        event_acts.clean_fields(data)


def test_decode_signature_accepts_a_drawing_and_rejects_the_rest():
    assert event_acts.decode_signature(_png()).startswith(b"\x89PNG")
    for bad in (_png(blank=True), "data:image/jpeg;base64,AAAA", "no es imagen", "data:image/png;base64,@@@", ""):
        with pytest.raises(ValueError):
            event_acts.decode_signature(bad)


def test_status_and_hash():
    a = SimpleNamespace(coordinator_sig_key=None, client_sig_key=None)
    assert event_acts.status_of(a) == "borrador"
    a.client_sig_key = "k"
    assert event_acts.status_of(a) == "firma_pendiente"
    a.coordinator_sig_key = "k"
    assert event_acts.status_of(a) == "firmada"
    assert event_acts.content_hash("a", "text", "b") != event_acts.content_hash("a", "text", "c")


def test_printable_html_escapes_and_embeds_signatures():
    act = SimpleNamespace(title="<b>T</b>", format="list", body="<script>x</script>\ndos", created_at=None, coordinator_name="Ana", coordinator_signed_at=None, coordinator_sig_key="k",
                          client_name=None, client_signed_at=None, client_sig_key=None, content_hash="abc")
    event = SimpleNamespace(name="Evento <1>", event_code="E1")
    out = event_acts.render_html(event, act, event_acts.decode_signature(_png()), None, company="ACME")
    assert "<script>" not in out and "&lt;script&gt;" in out and "&lt;b&gt;T" in out and "data:image/png;base64," in out and "Pendiente de firma" in out and out.count("<li>") == 2


# ------------------------------------------------------------------ texto (código fuente)
def test_routes_are_sync_and_guard_archived_base():
    src = (ROOT / "app" / "routers" / "event_acts.py").read_text(encoding="utf-8")
    assert "async def" not in src and "require_data_open" in src and "get_event_for_staff" in src
    assert 'staff.role == "cliente"' in src          # el cliente firma solo la suya
    assert "print(" not in src and "log." not in src and "logging" not in src


def test_migration_0126_is_linked_and_page_has_no_inline_js():
    mig = (ROOT / "alembic" / "versions" / "0126_event_acts.py").read_text(encoding="utf-8")
    assert 'revision = "0126_event_acts"' in mig and "event_acts" in mig
    tpl = (ROOT / "templates" / "kiosk_actas.html").read_text(encoding="utf-8")
    assert "<script>" not in tpl and not re.search(r'\sstyle="|\son(?:click|change|submit)=', tpl)


# ------------------------------------------------------------------ con base
@pytest.fixture()
def acta_env(client, factory):
    coord = factory.staff("coordinador", "coordA", tenant_id="acme", full_name="Carla Coordinadora")
    cli = factory.staff("cliente", "cliA", tenant_id="acme", full_name="Cesar Cliente")
    dig = factory.staff("digitador", "digA", tenant_id="acme")
    ev = factory.event("en_proceso", coordinator=coord)
    factory.authorize(ev, cli)
    factory.authorize(ev, dig)
    return ev, coord, cli, dig


def _as(client, user):
    from tests.conftest import login
    client.cookies.clear()
    assert login(client, user.username).status_code in (200, 302, 303)


def test_full_flow_two_signatures_lock_the_text(client, acta_env):
    ev, coord, cli, dig = acta_env
    base = f"/api/events/{ev.id}/acts"
    _as(client, coord)
    r = client.post(base, json={"title": "Día 1", "format": "list", "body": "Llegó tarde el sonido\nSe resolvió"})
    assert r.status_code == 200 and r.json()["status"] == "borrador"
    aid = r.json()["id"]
    assert client.post(f"{base}/{aid}/sign", json={"signature": _png(blank=True)}).status_code == 422
    r = client.post(f"{base}/{aid}/sign", json={"signature": _png()})
    assert r.status_code == 200 and r.json()["status"] == "firma_pendiente" and r.json()["coordinator_name"] == "Carla Coordinadora"
    assert client.post(f"{base}/{aid}/sign", json={"signature": _png()}).status_code == 409          # no firma dos veces
    # cambiar el texto con una firma puesta pide confirmación y la quita
    new = {"title": "Día 1", "format": "list", "body": "Otro texto"}
    assert client.put(f"{base}/{aid}", json=new).status_code == 409
    r = client.put(f"{base}/{aid}", json={**new, "confirm_reset": True})
    assert r.status_code == 200 and r.json()["status"] == "borrador"
    client.post(f"{base}/{aid}/sign", json={"signature": _png()})
    # el cliente firma solo la suya
    _as(client, cli)
    assert client.post(base, json={"title": "x", "body": "y"}).status_code == 403
    assert client.get(base).json()["is_client"] is True
    r = client.post(f"{base}/{aid}/sign", json={"signature": _png()})
    assert r.status_code == 200 and r.json()["status"] == "firmada" and r.json()["client_name"] == "Cesar Cliente"
    assert client.get(f"{base}/{aid}/signature/client").headers["content-type"] == "image/png"
    assert "Cesar Cliente" in client.get(f"{base}/{aid}/print").text
    # firmada: ni se edita ni se borra
    _as(client, coord)
    assert client.put(f"{base}/{aid}", json=new).status_code == 409
    assert client.delete(f"{base}/{aid}").status_code == 409


def test_digitador_has_no_access_and_unsigned_draft_can_be_deleted(client, acta_env):
    ev, coord, cli, dig = acta_env
    base = f"/api/events/{ev.id}/acts"
    _as(client, dig)
    assert client.get(base).status_code == 403
    _as(client, coord)
    aid = client.post(base, json={"title": "Borrador", "body": "texto"}).json()["id"]
    assert client.delete(f"{base}/{aid}").status_code == 200
    assert client.get(f"{base}/{aid}").status_code == 404
    assert client.get(f"/kiosk/{ev.id}/actas").status_code == 200
