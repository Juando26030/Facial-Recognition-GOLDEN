"""Fase 6: «Actualizar ahora» en un servidor local (app/local_update.py): reglas, petición para el servicio de actualización y estado."""
import json

import pytest

from app import local_update as lu
from app import versioning
from tests.conftest import login

GOOD = {"available": True, "commit": "bbb", "schema": "0111_event_lease", "package_url": "https://example.com/p.zip", "sha256": "a" * 64}
OLD = {"configured": True, "status": "desactualizada", "message": "x", "local": {"commit": "aaa", "schema": "0110_notifications"}, "production": {}}


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_SERVER", "1")
    monkeypatch.setenv("NODE_TOKEN", "gwn_test")          # servidor ya vinculado (sin vincular, el primer ingreso intenta vincularse con producción)
    monkeypatch.setenv("LOCAL_UPDATE_DIR", str(tmp_path))
    monkeypatch.setattr(versioning, "check", lambda force=False: OLD)
    monkeypatch.setattr(lu, "fetch_manifest", lambda timeout=4.0: dict(GOOD))
    return tmp_path


def test_published_manifest_needs_https_and_a_valid_hash(monkeypatch):
    monkeypatch.delenv("UPDATE_PACKAGE_URL", raising=False)
    assert lu.published_manifest()["available"] is False
    monkeypatch.setenv("UPDATE_PACKAGE_URL", "http://inseguro/p.zip")
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "a" * 64)
    assert lu.published_manifest()["available"] is False and lu.published_manifest()["package_url"] is None
    monkeypatch.setenv("UPDATE_PACKAGE_URL", "https://ok/p.zip")
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "xyz")
    assert lu.published_manifest()["available"] is False
    monkeypatch.setenv("UPDATE_PACKAGE_SHA256", "A" * 64)
    m = lu.published_manifest()
    assert m["available"] is True and m["sha256"] == "a" * 64 and m["package_url"] == "https://ok/p.zip"


def test_validate_manifest():
    assert lu.validate_manifest(dict(GOOD)) is None
    assert lu.validate_manifest(None) and lu.validate_manifest({"available": False})
    assert lu.validate_manifest({**GOOD, "package_url": "http://x/p.zip"})
    assert lu.validate_manifest({**GOOD, "sha256": "12"})
    assert lu.validate_manifest({**GOOD, "schema": "desconocida"})


def test_shift_rule():
    assert lu.shift_in_progress(1, 5) is True
    assert lu.shift_in_progress(1, 0) is False and lu.shift_in_progress(0, 9) is False


def test_request_writes_the_file_and_pending_status(local):
    assert lu.request_update(staff_id=3, events_in_progress=0, recent_checkins=0) == {"state": "pending"}
    req = json.loads((local / lu.REQUEST_FILE).read_text(encoding="utf-8"))
    assert req["package_url"] == GOOD["package_url"] and req["sha256"] == "a" * 64 and req["by_staff_id"] == 3 and req["from_schema"] == "0110_notifications"
    assert lu.read_status()["state"] == "pending" and lu.is_busy()
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=3, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "busy"


def test_refuses_in_the_cloud_when_up_to_date_or_without_a_package(local, monkeypatch):
    monkeypatch.setattr(versioning, "check", lambda force=False: {**OLD, "status": "igual"})
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "up_to_date"
    monkeypatch.setattr(versioning, "check", lambda force=False: OLD)
    monkeypatch.setattr(lu, "fetch_manifest", lambda timeout=4.0: {"available": False})
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "bad_manifest"
    monkeypatch.delenv("LOCAL_SERVER")
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=0, recent_checkins=0)
    assert e.value.code == "not_local"


def test_a_shift_in_progress_needs_explicit_confirmation(local):
    with pytest.raises(lu.UpdateRefused) as e:
        lu.request_update(staff_id=1, events_in_progress=1, recent_checkins=4)
    assert e.value.code == "shift_active" and not (local / lu.REQUEST_FILE).exists()           # sin confirmar no se deja nada
    assert lu.request_update(staff_id=1, events_in_progress=1, recent_checkins=4, confirm_shift=True)["state"] == "pending"
    assert json.loads((local / lu.REQUEST_FILE).read_text(encoding="utf-8"))["confirmed_during_shift"] is True


def test_read_status_ignores_garbage(tmp_path):
    (tmp_path / lu.STATUS_FILE).write_text("{no json", encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "idle"
    (tmp_path / lu.STATUS_FILE).write_text(json.dumps({"state": "inventado"}), encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "idle"
    (tmp_path / lu.STATUS_FILE).write_text(json.dumps({"state": "migrate", "message": "m"}), encoding="utf-8")
    assert lu.read_status(tmp_path)["state"] == "migrate"


def test_endpoints(client, factory, db, local):
    factory.staff("coordinador", "coord")
    factory.staff("digitador", "dig")
    assert client.get("/api/ops/update-manifest").status_code == 200
    login(client, "dig")
    assert client.post("/api/ops/update", json={}).status_code == 403
    client.get("/logout")
    login(client, "coord")
    assert client.get("/api/ops/update-status").json()["enabled"] is True
    r = client.post("/api/ops/update", json={})
    assert r.status_code == 200 and r.json()["state"] == "pending", r.text
    assert client.post("/api/ops/update", json={}).status_code == 409


def test_status_endpoint_is_disabled_in_the_cloud(client, factory, db, monkeypatch):
    monkeypatch.delenv("LOCAL_SERVER", raising=False)
    factory.staff("coordinador", "coord")
    login(client, "coord")
    assert client.get("/api/ops/update-status").json() == {"enabled": False}


def test_auto_update_respects_flag_and_shift(local, monkeypatch):
    class Q:
        def __init__(self, n): self.n = n
        def filter(self, *a): return self
        def count(self): return self.n
    class DB:
        def __init__(self, ev, rc): self.ev, self.rc = ev, rc
        def query(self, m): return Q(self.ev if m.__name__ == "Event" else self.rc)
    monkeypatch.setenv("AUTO_UPDATE", "0")
    assert lu.auto_update(DB(0, 0)) == "disabled"
    monkeypatch.setenv("AUTO_UPDATE", "1")
    assert lu.auto_update(DB(1, 5)) == "shift_active"
    assert lu.auto_update(DB(0, 0)) == "pending"


def test_catalog_write_blocked_only_in_local():
    from app import localmode as lm
    assert lm.is_catalog_write("POST", "/api/inventory/products")
    assert lm.is_catalog_write("PATCH", "/api/inventory/products/3/manage")
    assert not lm.is_catalog_write("GET", "/api/inventory/products")
    assert not lm.is_catalog_write("POST", "/api/events/1/inventory-deliver")


def test_manifest_falls_back_to_the_package_in_storage(monkeypatch):
    """Sin variables fijas a mano, producción publica el paquete más nuevo del almacenamiento y lo sirve ella misma (no hay que tocar variables en cada versión)."""
    monkeypatch.delenv("UPDATE_PACKAGE_URL", raising=False)
    monkeypatch.delenv("UPDATE_PACKAGE_SHA256", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(lu, "storage_package", lambda: ("golden-local-update-2026.11.18c.zip", "c" * 64))
    m = lu.published_manifest()
    assert m["available"] is True and m["sha256"] == "c" * 64
    assert m["package_url"] == "https://app.example.com/api/ops/update-package/golden-local-update-2026.11.18c.zip"
    monkeypatch.setattr(lu, "storage_package", lambda: None)
    assert lu.published_manifest()["available"] is False
    assert lu.package_bytes("../../etc/passwd") is None


def test_manifest_anuncia_el_commit_del_paquete_y_no_ofrece_uno_viejo(monkeypatch):
    """Si el paquete publicado es de otro commit que producción, no hay actualización disponible («se está preparando»); si coincide, se anuncia su commit."""
    monkeypatch.delenv("UPDATE_PACKAGE_URL", raising=False)
    monkeypatch.delenv("UPDATE_PACKAGE_SHA256", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(lu.versioning, "local_version", lambda: {"commit": "cb7e66374390", "date": "x", "schema": "0156_x"})
    monkeypatch.setattr(lu, "storage_package", lambda: ("golden-local-update-2026.11.18.100.zip", "a" * 64, "9f869cbebec2" + "0" * 28))
    m = lu.published_manifest()
    assert m["available"] is False and m["pending"] is True and m["package_url"] is None
    monkeypatch.setattr(lu, "storage_package", lambda: ("golden-local-update-2026.11.19.100.zip", "b" * 64, "cb7e66374390" + "1" * 28))
    m = lu.published_manifest()
    assert m["available"] is True and m["sha256"] == "b" * 64 and m["commit"].startswith("cb7e66374390")


def test_same_commit_acepta_abreviados_y_rechaza_distintos():
    assert lu.same_commit("cb7e66374390", "cb7e66374390" + "a" * 28)
    assert not lu.same_commit("cb7e66374390", "9f869cbebec2")
    assert not lu.same_commit(None, "cb7e66374390") and not lu.same_commit("abc", "abc")


def test_el_despliegue_publica_el_paquete_y_el_actualizador_verifica_el_commit():
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    sh = (raiz / "deploy" / "gcp" / "manual_deploy.sh").read_text(encoding="utf-8")
    assert "UPDATE_ONLY=1" in sh and "system/local-update/" in sh and "update-manifest" in sh
    assert "UPDATE_ONLY" in (raiz / "deploy" / "windows" / "build_cross.py").read_text(encoding="utf-8")
    assert "otra versión" in (raiz / "deploy" / "windows" / "run-update.ps1").read_text(encoding="utf-8")


def test_modo_local_bloquea_facial_y_paginas_solo_nube():
    from app import localmode as lm

    assert lm.is_face_call("POST", "/api/recognize") and lm.is_face_call("POST", "/api/recognize/candidates")
    assert lm.is_face_call("POST", "/api/events/19/enroll-face")
    assert not lm.is_face_call("GET", "/api/recognize") and not lm.is_face_call("POST", "/api/checkin-cedula")
    for ruta in ("/inventario", "/inventario/etiquetas", "/gastos", "/cuentas-de-cobro"):
        assert lm.is_cloud_only_page("GET", ruta)
    assert not lm.is_cloud_only_page("GET", "/eventos") and not lm.is_cloud_only_page("GET", "/kiosk/19/inventario")
    assert not lm.is_cloud_only_page("POST", "/inventario")


def test_checklist_de_inventario_foto_local(monkeypatch):
    """La foto del checklist se serializa y se vuelve a leer tal cual; una foto dañada se ignora."""
    import json
    from types import SimpleNamespace as NS

    from app import event_checklist as ec

    guardado = {}

    class FakeDB:
        def get(self, _model, key):
            return guardado.get(key)

        def add(self, row):
            guardado[row.key] = row

    monkeypatch.setattr(ec, "AppSetting", lambda key, value, updated_at: NS(key=key, value=value, updated_at=updated_at))
    db = FakeDB()
    ec.save_snapshot(db, 7, [{"name": "Portátil", "assigned": 2}])
    assert ec.load_snapshot(db, 7)["lines"] == [{"name": "Portátil", "assigned": 2}]
    guardado["evinv:7"].value = "{no es json"
    assert ec.load_snapshot(db, 7) is None
    assert ec.snapshot_key(7) == "evinv:7" and json.loads('{"lines": []}')["lines"] == []


def test_local_bloquea_el_rostro_en_parametros_y_no_muestra_sin_conexion_por_falta_de_internet():
    """19-nov-2026: en el servidor local «Usa rostro» está bloqueado (pantalla y servidor) y la falta de internet no se muestra como «Sin conexión» en Registro."""
    import pathlib
    tpl = pathlib.Path("templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert 'id="bsFacial" value="on"' in tpl and "{% if local_server %} disabled{% endif %}" in tpl and "data-local-nofacial" in tpl
    api = pathlib.Path("app/routers/consents.py").read_text(encoding="utf-8")
    assert "localmode.is_local_server()" in api and "LOCAL_NO_FACE_MSG" in api
    reg = pathlib.Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    assert "navigator.onLine === false && !LOCAL_NODE" in reg
    js = pathlib.Path("static/js/kiosk-alistamiento.js").read_text(encoding="utf-8")
    assert "load(true, true)" in js          # al abrir, el inventario se pone al día solo si hay internet


def test_local_muestra_la_ip_para_conectar_y_apaga_el_rostro_de_eventos_ya_descargados():
    """19-nov-2026: «Conectar: IP:puerto» junto a la versión; el rostro de eventos descargados antes se apaga solo; el checklist de inventario se refresca con internet."""
    import pathlib
    ops = pathlib.Path("app/routers/ops.py").read_text(encoding="utf-8")
    assert '"/api/ops/local-address"' in ops and "localmode.lan_address_details()" in ops          # 25-nov-2026: con el tipo de conexión (cable / Wi‑Fi)
    js = pathlib.Path("static/js/version-banner.js").read_text(encoding="utf-8")
    assert "/api/ops/local-address" in js and "Conectar:" in js and "gw-versionbar--info" in js and "gwver" in js
    main = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "enforce_no_face" in main
    lm = pathlib.Path("app/localmode.py").read_text(encoding="utf-8")
    assert "def enforce_no_face" in lm and "def lan_addresses" in lm
    ns = pathlib.Path("app/node_sync.py").read_text(encoding="utf-8")
    assert "_refresh_checklists(db)" in ns
    inst = pathlib.Path("deploy/windows/install.ps1").read_text(encoding="utf-8")
    assert "-LocalPort $AppPort" in inst and "LocalSubnet" in inst          # el puerto queda abierto para la red local
