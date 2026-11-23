"""Correcciones de seguridad del 22-nov-2026 (docs/revision_2026-11-22/12_seguridad_correcciones.md). Pruebas PURAS y de texto: sin base, sin FastAPI.
    python3 -m pytest --noconftest -q tests/test_seguridad_correcciones_2026-11-22.py
Las que necesitan base están en tests/test_seguridad_correcciones_bd.py."""
import ast
import pathlib
import re

from app import server_lock

SRC = pathlib.Path(__file__).resolve().parent.parent


def _read(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def _func(rel, name, extra=None):
    """Una función PURA de un módulo que aquí no se puede importar (FastAPI/SQLAlchemy): se compila sola desde su código."""
    tree = ast.parse(_read(rel))
    ns = dict(extra or {})
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            exec(compile(ast.Module(body=[node], type_ignores=[]), rel, "exec"), ns)          # noqa: S102 — código del propio repo
            return ns[name]
    raise AssertionError(f"{name} no está en {rel}")


def _body(rel, name):
    for node in ast.walk(ast.parse(_read(rel))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(_read(rel), node)
    raise AssertionError(f"{name} no está en {rel}")


# ------------------------------------------------------------------ 1. servidor local con alcance por cliente (0163)
def test_migracion_0163_es_aditiva_y_corta():
    src = _read("alembic/versions/0163_local_nodes_tenant.py")
    assert 'revision = "0163_local_nodes_tenant"' in src and len("0163_local_nodes_tenant") <= 32
    assert "local_nodes" in src and "local_server_keys" in src and "nullable=True" in src
    assert 'down_revision = "0162_organizations"' in src          # una sola cabeza (0162 es de otra pieza de la misma revisión)
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    assert "drop_" not in up and "alter_column" not in up and "SET " not in up
    models = _read("app/models.py")
    node = models.split("class LocalNode(Base)")[1].split("\nclass ")[0]
    key = models.split("class LocalServerKey(Base)")[1].split("\nclass ")[0]
    assert "tenant_id = Column(String, nullable=True)" in node and "tenant_id = Column(String, nullable=True)" in key


def test_nodo_sin_cliente_no_tiene_restriccion_y_con_cliente_solo_el_suyo():
    allows = _func("app/routers/node_api.py", "node_tenant_allows")
    assert allows(None, "acme") and allows("", "acme")                       # lo instalado antes de 0163: como siempre
    assert allows("acme", "acme") and not allows("acme", "otro") and not allows("acme", None)


def test_toda_ruta_de_nodo_con_evento_pasa_por_el_filtro_de_cliente():
    src = _read("app/routers/node_api.py")
    for fn in ("node_package", "node_inventory_checklist", "node_take_lease", "node_abort", "node_precheck", "node_changes"):
        body = _body("app/routers/node_api.py", fn)
        assert "_event_for_node(db, node, event_id" in body, fn
        assert not re.search(r"[^_]_event\(db, event_id", body), fn
    assert "Event.tenant_id == node.tenant_id" in _body("app/routers/node_api.py", "node_events")
    assert 'status_code=404, detail="Evento no encontrado"' in _body("app/routers/node_api.py", "_event_for_node")          # 404, no 403: no revela eventos ajenos
    assert src.count("node_tenant_allows(") >= 2
    nodes = _read("app/routers/nodes.py")
    assert "node_tenant_allows(" in _body("app/routers/nodes.py", "_leased_event")          # devolver, sincronizar, «uploaded», records, extra
    assert "tenant_id=key.tenant_id" in _body("app/routers/nodes.py", "enroll_node")       # el servidor hereda el cliente de su llave
    assert "node.tenant_id)" in nodes.split("async def node_backup(")[1]


def test_llave_con_cliente_opcional_y_ayuda_dummy():
    api = _body("app/routers/server_keys.py", "create_key")
    assert '.get("tenant_id")' in api and "archived_at is not None" in api and "tenant_id=tenant_id" in api
    html = _read("templates/configuracion.html")
    card = html.split('id="serverKeysCard"')[1].split('id="localInstallerPublish"')[0]
    assert 'id="skTenant"' in card and '<option value="">Todos los clientes' in card
    help_text = card.split("ay_sk_tenant")[1].split("endcall")[0]
    for part in ("Qué es", "Para qué sirve", "Si eliges un cliente", "Si lo dejas", "Ejemplo", "Qué NO hace"):          # principio dummy
        assert part in help_text, part
    assert "onclick" not in card and "style=" not in card
    js = _read("static/js/server-keys-card.js")
    assert "tenant_id: tenantSel ? tenantSel.value : ''" in js and "/api/tenants" in js
    assert "alert(" not in js and "innerHTML" not in js


# ------------------------------------------------------------------ 2. lo que sube un servidor: solo asistentes del evento
def test_node_extra_exige_asistente_del_evento_solo_en_la_nube():
    src = _read("app/node_extra.py")
    assert "EventAttendee.event_id == event.id" in _body("app/node_extra.py", "is_attendee")
    assert "return event if from_peer is None else None" in _body("app/node_extra.py", "_strict")          # al BAJAR de la nube (from_peer=True) no se filtra
    for fn in ("apply_edits", "apply_acceptances", "apply_consents"):
        assert "_Users(db, event.tenant_id, _strict(event, from_peer), stats)" in _body("app/node_extra.py", fn), fn
    effect = _body("app/node_extra.py", "apply_person_change_effect")
    assert "attendee_only and not is_attendee(db, event, uid)" in effect
    assert '"rejected": stats["rejected"]' in _body("app/node_extra.py", "apply_all")
    rec = _body("app/routers/nodes.py", "node_records")
    assert "attendee_only=True, stats=stats" in rec and '"rejected": stats["rejected"]' in rec
    assert '"rejected"' in _body("app/routers/nodes.py", "node_extra_upload")
    assert src.count("UPDATE") == 0 and "audit_consent_logs" in src          # la tabla de autorizaciones sigue siendo solo INSERT


def test_aceptacion_biometrica_de_un_nodo_queda_por_verificar_con_la_marca_existente():
    body = _body("app/node_extra.py", "apply_consents")
    assert "hold = (from_peer is None and reason == \"consent\" and row[\"accepted_biometric\"]" in body
    assert "not consent.has_acceptance(db, event.tenant_id, uid, event.id)" in body          # quien ya tenía una vigente no se «des-verifica»
    assert "WebAcceptance(tenant_id=event.tenant_id, user_id=uid, event_id=event.id, created_at=at, verified_at=None)" in body
    assert "verified_at IS NULL" in _read("app/consent.py")          # la marca que excluye del reconocimiento ya existía: no se inventó otra
    all_ = _body("app/node_extra.py", "apply_all")
    assert all_.index("apply_acceptances(") < all_.index("apply_consents(")          # primero la verificación que subió el mismo servidor


# ------------------------------------------------------------------ 3. servidor vinculado por coordinador/comercial
def test_quien_puede_vincular_puede_subir():
    can = _func("app/node_auth.py", "staff_can_upload", {"ENROLL_ROLES": ("coordinador", "comercial", "admin", "super_admin")})
    for role in ("coordinador", "comercial", "admin", "super_admin"):
        assert can(role)
    assert can("digitador", {"digitador", "comercial"})                       # rol sumado
    assert not can("digitador") and not can("cliente") and not can("almacen")
    assert not can("admin", is_active=False) and not can("admin", archived=True) and not can("coordinador", event_only=True)
    assert 'ENROLL_ROLES = ("coordinador", "comercial", "admin", "super_admin")' in _read("app/node_auth.py")
    nodes = _read("app/routers/nodes.py")
    assert "ENROLL_ROLES = node_auth.ENROLL_ROLES" in nodes          # una sola lista
    helper = _body("app/routers/nodes.py", "_upload_staff")
    assert 'staff.role not in ("admin", "super_admin")' in helper and "get_event_for_staff(event.id, db, staff)" in helper
    assert "_upload_staff(db, node, event)" in _body("app/routers/nodes.py", "node_records") and "_upload_staff(db, node, event)" in _body("app/routers/nodes.py", "node_extra_upload")


# ------------------------------------------------------------------ 5. «tomar» un trabajo de impresión: POST (GET en transición)
def test_print_jobs_next_acepta_post_y_el_js_llama_por_post():
    src = _read("app/routers/shared_print.py")
    block = src.split("def next_job(")[0][-600:]
    assert '@router.post("/events/{event_id}/print-jobs-next")' in block and '@router.get("/events/{event_id}/print-jobs-next")' in block
    assert "_require_page_fetch(request)" in _body("app/routers/shared_print.py", "next_job")          # la defensa del GET se conserva mientras exista
    js = _read("static/js/shared-print.js")
    calls = [ln for ln in js.splitlines() if "print-jobs-next" in ln and "fetchT(" in ln]
    assert len(calls) == 2 and all("method: 'POST'" in ln and "'X-Gw-Fetch': '1'" in ln for ln in calls)


# ------------------------------------------------------------------ 6. dependencias
def test_setuptools_sin_cve_conocidos_y_con_pkg_resources():
    line = next(ln for ln in _read("requirements.txt").splitlines() if ln.startswith("setuptools=="))
    version = tuple(int(x) for x in line.split("==")[1].split()[0].split("."))
    assert (78, 1, 1) <= version < (82,)          # ≥ 78.1.1 (CVE-2025-47273) y < 82 (desaparece pkg_resources)
    pins = {ln.split("==")[0]: ln.split("==")[1].split()[0].rstrip(";") for ln in _read("requirements.txt").splitlines() if "==" in ln and not ln.startswith("#")}
    assert pins["fastapi"].startswith("0.141.") and pins["SQLAlchemy"].startswith("2.0.") and pins["dlib"].startswith("20.")          # sin saltos de versión mayor


# ------------------------------------------------------------------ 7. plazo de gracia del servidor local sin nube
DAY = 86400


def test_regla_de_gracia_sin_nube():
    d = server_lock.grace_decision
    now = 1_800_000_000
    assert d(now, now - 2 * DAY, None, 0, 14)["state"] == "ok"
    assert d(now, now - 12 * DAY, None, 0, 14)["state"] == "warn" and d(now, now - 12 * DAY, None, 0, 14)["days_left"] == 2
    out = d(now, now - 14 * DAY, None, 0, 14)
    assert out["state"] == "readonly" and out["reason"] == "offline" and "SOLO LECTURA" in out["message"]
    assert d(now, now - 400 * DAY, None, 0, 0)["state"] == "ok"                 # LOCAL_GRACE_DAYS=0: apagado
    assert d(now, None, None, 0, 14)["state"] == "ok"                           # sin marca: el reloj apenas empieza
    assert d(now, now - 3600, None, 0, 1)["state"] == "ok"                      # nunca el mismo día


def test_token_revocado_avisa_hoy_y_solo_lectura_al_dia_siguiente():
    d = server_lock.grace_decision
    now = 1_800_000_000
    assert d(now, now - 60, now - 60, 1, 14)["state"] == "ok"                   # un 401 suelto no cuenta
    out = d(now, now - 60, now - 3600, server_lock.REVOKED_PINGS, 14)
    assert out["state"] == "warn" and out["reason"] == "revoked"                # el mismo día: la puerta sigue, con aviso
    assert d(now, now - 60, now - 25 * 3600, server_lock.REVOKED_PINGS, 14)["state"] == "readonly"


def test_marcas_de_gracia_en_local_env(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    f.write_text("NODE_TOKEN=gwn_x\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_ENV_FILE", str(f))
    monkeypatch.delenv("SERVER_DISABLED", raising=False)
    monkeypatch.delenv("LOCAL_GRACE_DAYS", raising=False)
    server_lock._cache.update(at=0.0, locked=False)
    server_lock._grace.update(at=0.0, marks=None, saved_ok=0.0, dirty_401=True)
    assert server_lock.grace_days() == 14
    assert server_lock.grace_state()["state"] == "ok" and "LOCAL_CLOUD_OK_AT=" in f.read_text(encoding="utf-8")          # servidor ya instalado: el reloj empieza al actualizar
    assert server_lock.grace_state(now_ts=__import__("time").time() + 15 * DAY)["state"] == "readonly"
    for _ in range(server_lock.REVOKED_PINGS + 2):
        server_lock.note_cloud_error(401, "Servidor local no autorizado")
    assert f"LOCAL_CLOUD_401_N={server_lock.REVOKED_PINGS}" in f.read_text(encoding="utf-8")
    assert server_lock.grace_state()["state"] == "warn" and server_lock.is_locked() is False          # 401 nunca «deshabilita»: eso es solo el 403 con el texto fijo
    server_lock.note_cloud_ok()                                                                      # la nube lo volvió a reconocer: todo se restablece solo
    assert "LOCAL_CLOUD_401_N=0" in f.read_text(encoding="utf-8") and server_lock.grace_state()["state"] == "ok"
    assert "NODE_TOKEN=gwn_x" in f.read_text(encoding="utf-8")                                        # el resto de local.env no se toca
    monkeypatch.setenv("LOCAL_GRACE_DAYS", "0")
    assert server_lock.grace_state(now_ts=9e12)["state"] == "ok"


def test_solo_lectura_deja_entrar_y_subir_lo_pendiente():
    w = server_lock.write_blocked
    assert w("POST", "/api/register", "readonly") and w("DELETE", "/api/users/1", "readonly") and w("PATCH", "/api/events/3", "readonly")
    assert not w("GET", "/api/users", "readonly") and not w("POST", "/api/register", "warn") and not w("POST", "/api/register", "ok")
    for path in ("/login", "/logout", "/api/node-sync/run", "/api/node-sync/events/3/release", "/api/local/cloud-events/3/download", "/health"):
        assert not w("POST", path, "readonly"), path
    assert "server_lock.note_cloud_ok()" in _body("app/node_sync.py", "_call")


def test_pendiente_4_no_se_implemento_a_medias():
    """03 #4 (/aceptar, foto pendiente) NO se tocó: hace falta cambiar la purga biométrica (app/privacy.py) en la misma pieza. Si alguien lo implementa, esta prueba le recuerda la regla."""
    src = _read("app/routers/aceptar.py")
    if "pending" in src:
        privacy = _read("app/privacy.py")
        assert "pending" in privacy, "una foto pendiente de /aceptar debe borrarse en TODA purga biométrica (retención de 7 días)"


def test_grace_period_is_wired_into_the_middleware_and_the_banner():
    main = _read("app/main.py")
    mid = main.split("async def local_catalog_readonly")[1].split("@app.middleware")[0]
    assert "server_lock.grace_state()" in mid and "server_lock.write_blocked(request.method, request.url.path, grace[\"state\"])" in mid
    assert mid.index("is_locked()") < mid.index("grace_state()") < mid.index("is_catalog_write")
    assert '"grace"' in _read("app/routers/ops.py")
    assert "s.grace.message" in _read("static/js/version-banner.js")


def test_disabling_a_key_triggers_the_automatic_wipe_and_asks_to_type_the_word():
    upd = _read("deploy/windows/updater-service.ps1")
    assert "SERVER_DISABLED" in upd and "LOCAL_WIPE_ON_DISABLE" in upd and "SERVER_WIPE_STARTED" in upd and "autodestruir.ps1" in upd
    wipe = _read("deploy/windows/autodestruir.ps1")
    assert "borrar-datos.ps1" in wipe and "-Yes" in wipe and "unins000.exe" in wipe and "rmdir /s /q" in wipe and "Unregister-ScheduledTask" in wipe
    card = _read("static/js/server-keys-card.js")
    assert "GWConfirm.typed(" in card and "'DESHABILITAR'" in card and "DESHABILITAR" in _read("static/js/gw-confirm-typed.js")


def test_bitlocker_script_never_buys_never_stores_the_key_on_the_encrypted_disk_and_asks_for_tpm():
    ps = _read("deploy/windows/proteger-disco.ps1")
    assert "Get-BitLockerVolume" in ps and "TpmPresent" in ps and "StartsWith($mount" in ps and "-RecoveryKeyFolder" in ps
    assert "Write-Log" not in ps and "Add-Content" not in ps          # la clave no va a ningún registro
