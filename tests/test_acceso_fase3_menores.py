"""Fase 3, endurecimientos pequeños de acceso: B11 (sibling-check con freno), B12 (badge-assets) y B14/B6 documentados en docs/FASE_3_SEGURIDAD.md."""
from tests.conftest import login


def test_sibling_check_is_rate_limited_per_account(client, factory, monkeypatch):
    from app.routers import super_events
    monkeypatch.setattr(super_events, "SIBLING_CHECK_MAX", 2)
    dig = factory.staff("digitador", "dig_sib")
    ev = factory.event("en_proceso")
    factory.authorize(ev, dig)
    login(client, "dig_sib")
    codes = [client.get(f"/api/users/{n}/sibling-check?event_id={ev.id}").status_code for n in ("1", "2", "3", "4")]
    assert codes[:2] == [200, 200] and codes[2] == 429 and codes[3] == 429


def test_badge_assets_are_refused_to_a_form_client_but_not_to_other_clients(client, factory, db):
    from app.models import FormClientUser, WebForm
    from app.storage import badge_asset_key, get_storage
    from app.timeutil import utcnow
    from datetime import timedelta
    ev = factory.event("en_proceso")
    get_storage().put(badge_asset_key(ev.tenant_id, "logo.png"), b"\x89PNG\r\n\x1a\n")
    form = WebForm(event_id=ev.id, name="F", slug="f", design_json="{}", test_key="k")
    db.add(form)
    db.commit()
    fc = factory.staff("cliente", "cli_form")
    ec = factory.staff("cliente", "cli_event")
    db.add(FormClientUser(staff_user_id=fc.id, form_id=form.id, expires_at=utcnow() + timedelta(days=1)))
    db.commit()
    login(client, "cli_event")
    assert client.get(f"/api/badge-assets/{ev.tenant_id}/logo.png").status_code == 200
    client.post("/logout")
    login(client, "cli_form")
    assert client.get(f"/api/badge-assets/{ev.tenant_id}/logo.png").status_code == 404
    assert ec.id != fc.id


def test_badge_assets_respect_the_tenant_when_enforced(client, factory, monkeypatch):
    from app.storage import badge_asset_key, get_storage
    ev = factory.event("en_proceso", tenant_id="otro")
    get_storage().put(badge_asset_key("otro", "logo.png"), b"\x89PNG\r\n\x1a\n")
    factory.staff("coordinador", "coord_acme", tenant_id="acme")
    login(client, "coord_acme")
    assert client.get(f"/api/badge-assets/{ev.tenant_id}/logo.png").status_code == 200          # apagado por defecto (hoy todo el personal es de Golden)
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    assert client.get(f"/api/badge-assets/{ev.tenant_id}/logo.png").status_code == 404
