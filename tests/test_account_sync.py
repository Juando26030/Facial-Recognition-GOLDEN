"""Fase 6: cuentas de la nube hacia el servidor local (hash, altas/bajas/roles) y contraseñas deshabilitadas en un servidor local."""
import copy

import pytest

from app import account_sync
from app.auth import hash_password, verify_password
from app.models import AppSetting, StaffUser
from tests.conftest import PASSWORD, login


def _payload(db):
    snap = account_sync.snapshot(db)
    return copy.deepcopy(snap)


def _reseal(p):
    p["version"] = account_sync.version_of(p["tenants"], p["staff"])
    return p


def test_snapshot_version_changes_with_any_account_change_and_delta_is_unchanged_when_same(db, factory):
    factory.staff("coordinador", "ana")
    v1 = account_sync.snapshot(db)["version"]
    assert account_sync.delta(db, v1) == {"unchanged": True, "version": v1}
    s = db.query(StaffUser).filter_by(username="ana").first()
    s.role = "comercial"
    db.commit()
    d = account_sync.delta(db, v1)
    assert d["unchanged"] is False and d["version"] != v1 and {r["username"] for r in d["staff"]} == {"ana"}


def test_snapshot_carries_the_hash_but_never_sessions_or_lock_state(db, factory):
    factory.staff("admin", "root")
    row = account_sync.snapshot(db)["staff"][0]
    assert row["password_hash"].startswith(("$", "pbkdf2", "argon")) or len(row["password_hash"]) > 20
    assert not ({"session_token", "failed_logins", "locked_at", "login_req_hash", "session_epoch"} & set(row))


def test_apply_creates_updates_and_deactivates_and_the_password_still_works(db, factory):
    factory.staff("admin", "root")
    factory.staff("coordinador", "vieja")
    factory.staff("coordinador", "cambia")
    p = _payload(db)
    for r in p["staff"]:
        if r["username"] == "cambia":
            r["role"], r["password_hash"] = "comercial", hash_password("Nueva#2026xx")
    p["staff"] = [r for r in p["staff"] if r["username"] != "vieja"]
    p["staff"].append({**p["staff"][0], "username": "nueva", "role": "almacen", "phone": "+573009999999", "password_hash": hash_password("Alma#2026xx")})
    counts = account_sync.apply(db, _reseal(p))
    db.commit()
    db.expire_all()
    assert counts["created"] == 1 and counts["updated"] >= 1 and counts["deactivated"] == 1
    by = {s.username: s for s in db.query(StaffUser).all()}
    assert by["cambia"].role == "comercial" and verify_password("Nueva#2026xx", by["cambia"].password_hash)
    assert by["nueva"].role == "almacen" and verify_password("Alma#2026xx", by["nueva"].password_hash)
    assert by["vieja"].is_active is False and by["vieja"].archived_at is not None          # no se borra: se desactiva
    assert account_sync.current_version(db) == p["version"] and db.get(AppSetting, account_sync.SYNCED_AT_KEY)


def test_apply_rejects_a_damaged_answer_and_never_leaves_the_server_without_an_active_account(db, factory):
    factory.staff("admin", "root")
    p = _payload(db)
    bad = copy.deepcopy(p)
    bad["staff"][0]["role"] = "digitador"                      # cambió algo sin recalcular la huella
    with pytest.raises(ValueError):
        account_sync.apply(db, bad)
    empty = copy.deepcopy(p)
    for r in empty["staff"]:
        r["is_active"] = False
    with pytest.raises(ValueError):
        account_sync.apply(db, _reseal(empty))
    db.rollback()
    assert db.query(StaffUser).filter_by(username="root").first().is_active is True


def test_apply_unchanged_does_nothing(db):
    assert account_sync.apply(db, {"unchanged": True}) == {"unchanged": True}


def test_endpoint_is_closed_without_a_valid_node_token(client, factory):
    factory.staff("admin", "root")
    login(client, "root")                                        # una sesión de persona NO sirve: hace falta el token del nodo
    assert client.get("/api/node/accounts").status_code in (401, 403, 422, 503)


def test_run_once_without_configuration_or_network_never_raises(db, monkeypatch):
    monkeypatch.delenv("PRODUCTION_URL", raising=False)
    monkeypatch.delenv("NODE_TOKEN", raising=False)
    assert account_sync.run_once(db) == {"ok": False, "reason": "sin_configurar"}
    monkeypatch.setenv("PRODUCTION_URL", "https://nube.example")
    monkeypatch.setenv("NODE_TOKEN", "t")
    monkeypatch.setattr(account_sync, "fetch", lambda *a, **k: None)
    assert account_sync.run_once(db) == {"ok": False, "reason": "sin_conexion"}


# ------------------------------------------------------------------ contraseñas: solo en la nube
def test_local_server_blocks_every_password_path_but_login_still_works(client, factory, monkeypatch):
    factory.staff("admin", "root")
    victim = factory.staff("coordinador", "coord", must_change_password=True)
    vid = victim.id
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("NODE_TOKEN", "gwn_test")          # servidor ya vinculado (sin vincular, el primer ingreso intenta vincularse con producción)
    r = client.post("/login", data={"username": "coord", "password": PASSWORD}, follow_redirects=False)
    assert r.status_code in (302, 303) and "/cambiar-contrasena" not in r.headers["location"]          # no se obliga a cambiarla
    assert client.post("/cambiar-contrasena", data={"current": PASSWORD, "password": "Otra#2026xyz", "confirm": "Otra#2026xyz"}).status_code == 403
    assert client.get("/cambiar-contrasena", follow_redirects=False).status_code in (302, 303)
    assert client.post("/olvide-contrasena", data={"username": "coord"}).status_code == 403
    client.get("/logout")
    login(client, "root")
    r = client.put(f"/api/staff/{vid}/password", json={"new_password": "Otra#2026xyz"})
    assert r.status_code == 403 and "solo se cambia en la nube" in r.json()["detail"]
    r = client.post("/api/staff", json={"username": "nuevo1", "password": "Otra#2026xyz", "role": "coordinador", "full_name": "N", "email": "n@example.com", "phone": "+573001112233"})
    assert r.status_code == 403
    monkeypatch.delenv("LOCAL_SERVER")
    assert client.put(f"/api/staff/{vid}/password", json={"new_password": "Otra#2026xyz"}).status_code == 200      # en la nube sigue igual


def test_f5_9_inactive_or_archived_accounts_travel_without_their_hash(db, factory):
    """F5-9 A-08: una cuenta desactivada o archivada no entrega su hash a ningún nodo (si el token se filtra, no hay hash que romper) y en el local no sirve para entrar."""
    from app.timeutil import utcnow
    factory.staff("admin", "root")
    off = factory.staff("coordinador", "baja")
    arch = factory.staff("coordinador", "archivada")
    off.is_active = False
    arch.archived_at = utcnow()
    db.commit()
    rows = {r["username"]: r for r in account_sync.snapshot(db)["staff"]}
    assert rows["baja"]["password_hash"] == account_sync.NO_PASSWORD == rows["archivada"]["password_hash"]
    assert rows["root"]["password_hash"] != account_sync.NO_PASSWORD
    assert verify_password(PASSWORD, account_sync.NO_PASSWORD) is False


def test_f5_9_local_server_never_creates_accounts(client, factory, db, monkeypatch):
    """F5-9 A-12 (regla de Juan David): en el servidor local no se crean digitadores (uno a uno ni por Excel) ni accesos de cliente de formulario."""
    factory.staff("admin", "root")
    ev = factory.event("en_proceso")
    ev_id = ev.id
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("NODE_TOKEN", "gwn_test")          # servidor ya vinculado
    login(client, "root")
    r = client.post(f"/api/events/{ev_id}/staff-users", json={"username": "99887766", "full_name": "Digi", "role": "digitador"})
    assert r.status_code == 403 and "nube" in r.json()["detail"]
    r = client.post(f"/api/events/{ev_id}/staff-users/import", files={"file": ("d.xlsx", b"x", "application/octet-stream")})
    assert r.status_code == 403
    assert db.query(StaffUser).filter_by(username="99887766").first() is None


# ------------------------------------------------------------------------------------------------ CRM C1a: el código de cliente pasa a número (alias hexadecimal)
def _cloud(db, factory):
    """La «nube»: un cliente con código hexadecimal y dos cuentas (una admin sin cliente y una coordinadora del cliente)."""
    from app.models import Tenant
    factory.tenant("acme")
    factory.staff("admin", "root")
    factory.staff("coordinador", "ana", tenant_id="acme")
    return db.query(Tenant).filter_by(id="acme").one()


def _tenant_row(p, tid="acme"):
    return next(t for t in p["tenants"] if t["id"] == tid)


def test_snapshot_carries_the_legacy_client_code(db, factory):
    t = _cloud(db, factory)
    t.legacy_client_code, t.client_code = t.client_code, "21500"
    db.commit()
    row = _tenant_row(account_sync.snapshot(db))
    assert row["client_code"] == "21500" and row["legacy_client_code"] == "Cacme"


def test_apply_updates_the_client_code_of_an_existing_tenant_without_duplicating_it(db, factory):
    from app.models import Tenant
    t = _cloud(db, factory)
    p = _payload(db)
    row = _tenant_row(p)
    row["legacy_client_code"], row["client_code"] = row["client_code"], "21500"
    account_sync.apply(db, _reseal(p))
    db.commit()
    db.expire_all()
    assert db.query(Tenant).count() == 1                                                         # el mismo cliente, no uno nuevo
    t = db.query(Tenant).filter_by(id="acme").one()
    assert t.client_code == "21500" and t.legacy_client_code == "Cacme"


def test_apply_creates_a_tenant_that_does_not_exist_here_with_its_number_and_alias(db, factory):
    from app.models import Tenant
    _cloud(db, factory)
    p = _payload(db)
    p["tenants"].append({**_tenant_row(p), "id": "nuevo", "client_code": "21501", "legacy_client_code": "HEXNUEVO", "name": "NUEVO"})
    for r in p["staff"]:
        if r["username"] == "ana":
            r["tenant_id"] = "nuevo"
    account_sync.apply(db, _reseal(p))
    db.commit()
    db.expire_all()
    t = db.query(Tenant).filter_by(id="nuevo").one()
    assert (t.client_code, t.legacy_client_code) == ("21501", "HEXNUEVO") and db.query(Tenant).count() == 2


def test_apply_accepts_a_payload_from_a_cloud_older_than_the_crm_and_keeps_the_alias_already_here(db, factory):
    from app.models import Tenant
    t = _cloud(db, factory)
    t.legacy_client_code = "ALIAS-VIEJO"
    db.commit()
    p = _payload(db)
    row = _tenant_row(p)
    row.pop("legacy_client_code")                                                                # la nube anterior no manda el campo
    row["client_code"] = "21500"
    account_sync.apply(db, _reseal(p))
    db.commit()
    db.expire_all()
    t = db.query(Tenant).filter_by(id="acme").one()
    assert t.client_code == "21500" and t.legacy_client_code == "ALIAS-VIEJO"
