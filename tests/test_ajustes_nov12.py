"""Ajustes del 12-nov-2026: cliente temporal del evento, «(opcional)» en negrilla y filas de lista que no se descuadran en ventanas angostas.
Pruebas «de texto» (leen el código fuente): corren sin base de datos."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _t(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_client_temp_migration_chain_and_id_length():
    mig = _t("alembic/versions/0129_staff_client_temp.py")
    rev = re.search(r'^revision = "([^"]+)"', mig, re.M).group(1)
    assert len(rev) <= 32 and 'down_revision = "0128_event_types"' in mig          # el id de Alembic no pasa de 32 caracteres
    assert '"client_temp"' in mig and "server_default" in mig                      # las cuentas que ya existen quedan en falso
    assert "client_temp = Column(Boolean" in _t("app/models.py")


def test_client_temp_skips_login_approval_but_keeps_digitador_role():
    lc = _t("app/login_control.py")
    applies = lc[lc.index("def applies"):lc.index("def token_hash")]
    assert 'staff.role == "digitador"' in applies and "client_temp" in applies       # el cliente temporal no pasa por la solicitud de ingreso
    ev = _t("app/routers/events.py")
    create = ev[ev.index("def create_event_staff"):ev.index("def assign_existing_staff")]
    assert 'role="digitador", client_temp=True' in create                              # mismos permisos que el digitador
    assert "temp_client.new_username" in create and "temp_client.new_password" in create
    assert '"credentials": {"username": username, "password": password}' in create    # se entregan una sola vez en esta respuesta
    assert "enqueue_for_event" not in create[:create.index("if not data.username")]    # la rama del cliente no manda correo (nunca lleva contraseña)


def test_client_temp_reset_generates_new_random_password():
    st = _t("app/routers/staff.py")
    reset = st[st.index("def reset_staff_password"):st.index("def deactivate_staff")]
    assert 'data.get("generate")' in reset and "temp_client.new_password" in reset
    assert '"new_password": generated' in reset
    assert "El cliente temporal no usa la cédula" in reset


def test_client_temp_generator_rules():
    src = _t("app/temp_client.py")
    assert "secrets.choice" in src and "random." not in src                              # aleatoriedad criptográfica
    assert 'USER_PREFIX = "cli-"' in src and "password_problem" in src                  # cumple la política estricta


def test_client_temp_screen():
    html = _t("templates/kiosk_usuarios.html")
    assert 'value="cliente_temp"' in html and 'id="clientCreds"' in html and 'id="uUsernameField"' in html
    js = _t("static/js/usuarios.js")
    assert "payload.client = true" in js and "showCredentials(d.credentials.username, d.credentials.password)" in js
    assert "u.client_temp" in js and "resetClientPassword" in js
    assert "Cliente (temporal)" in js
    assert "loginBtns = !canManage || u.role !== 'digitador' || u.client_temp" in js     # sin «Permitir/No permitir» para el cliente temporal


def test_optional_label_is_bold():
    js = _t("static/js/form-render.js")
    line = next(ln for ln in js.splitlines() if "const OPTIONAL" in ln)
    assert "font-weight:700" in line and "opacity" not in line


def test_list_rows_wrap_instead_of_overflowing():
    css = _t("static/css/p-formularios.css")
    assert "container: forms / inline-size" in css and "@container forms (min-width: 1240px)" in css


def test_form_files_helpers():
    from app import formfiles
    design = {"rows": [{"items": ["a", "b", "c"]}], "fields": {"a": {"type": "file", "label": "PDF ARL", "key": "opcional_2"}, "b": {"type": "text_short", "label": "x"}, "c": {"type": "file", "label": "Certificado"}}}
    assert formfiles.file_fields(design) == [("a", "PDF ARL"), ("c", "Certificado")]
    assert formfiles.extras_key_for(design, "a") == "opcional_2" and formfiles.extras_key_for(design, "c") is None
    assert formfiles.stored_text({"filename": "arl.pdf", "stored": "x"}) == "arl.pdf" and formfiles.stored_text("hola") == "hola"
    used = set()
    n1 = formfiles.zip_entry_name("1001", "PDF ARL", 1, "Mi Archivo.PDF", used)
    n2 = formfiles.zip_entry_name("1001", "PDF ARL", 7, "otro.pdf", used)
    assert n1 == "1001_PDF_ARL.pdf" and n2 != n1 and n2.endswith(".pdf")


def test_form_files_routes_and_screens():
    f = _t("app/routers/forms.py")
    assert '/forms/{form_id}/files-zip' in f and "formfiles.MAX_FILES" in f
    a = _t("app/routers/api.py")
    assert "/users/{user_id}/form-files" in a and 'require_role("digitador")' in a[a.index("def person_form_files"):a.index("def person_form_file_download")]
    assert 'require_role("digitador")' in a[a.index("def person_form_file_download"):a.index("def incomplete_registrations")]      # cliente temporal y digitador temporal también descargan; get_event_for_staff les exige estar autorizados en el evento
    assert "formfiles.stored_text" in _t("app/formsvc.py")
    assert "files-zip?field=" in _t("templates/kiosk_formulario_editor.html") and 'id="ansFiles"' in _t("templates/kiosk_formulario_editor.html")
    assert "/form-files`" in _t("static/js/directory.js")


def test_switch_to_realtime_feeds_existing_submissions():
    f = _t("app/routers/forms.py")
    assert "feed_before != \"realtime\"" in f and "enqueue_pending_feed" in f and "jobs.kick()" in f
    s = _t("app/formsvc.py")
    body = s[s.index("def enqueue_pending_feed"):s.index("def feed_pending")]
    assert "fed == False" in body and '"form_feed"' in body and "dedupe_key" in body
    assert "feed_queued" in _t("templates/kiosk_formulario_editor.html")


def test_servidor_local_lista_como_eventos_y_abre_el_kiosco():
    js = _t("static/js/servidor-local.js")
    assert "gw-event-card" in js and "p-cli__acts" in js and "Informe pendiente" in js          # la misma tarjeta que la lista de Eventos
    assert "href=\"/kiosk/${e.local_event_id}\"" in js and "/registro" not in js               # «Ingresar» lleva al kiosco, no al registro
    page = _t("templates/servidor_local.html")
    assert "p-clientes.css" in page and "gw-eventos.css" in page
    meta = _t("app/routers/node_api.py")
    assert "commercial_name" in meta and "coordinator_name" in meta and "report_uploaded" in meta
