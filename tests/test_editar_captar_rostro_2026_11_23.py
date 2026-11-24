"""Editar persona ofrece «Captar rostro» (solo con reconocimiento facial) y usa el mismo camino con aceptación de la persona."""
from pathlib import Path

R = Path(__file__).resolve().parent.parent


def test_boton_en_editar_y_camino_unico():
    d = (R / "static/js/directory.js").read_text(encoding="utf-8")
    a = (R / "static/js/app.js").read_text(encoding="utf-8")
    assert "editModalFace" in d and "window.GoldenFace" in d          # el botón solo existe si el escáner facial está en la página
    assert "window.GoldenFace = {" in a and "identify()" in a          # reutiliza identify(): la aceptación de la persona sigue siendo obligatoria
    assert "enroll-face" in a                                          # y la foto se guarda por el endpoint que exige aceptación


def test_setoff_se_define_antes_de_apagar_la_camara():
    """Regresión: `cameraOff()` corre al cargar y usa setOff/setResult; si se definen después, app.js se detiene (TDZ) y la cámara nunca enciende."""
    a = (R / "static/js/app.js").read_text(encoding="utf-8")
    assert a.index("const setOff =") < a.index("if (video) {") < a.index("        cameraOff();")
    assert a.index("const resTexto =") < a.index("const setResult =") < a.index("if (video) {")


def test_un_solo_boton_y_acreditada_no_pregunta():
    """23-nov-2026: la fila trae SU botón (Acreditar / Acreditado); la búsqueda por cédula no agrega otro, y una persona ya acreditada solo se avisa (en línea)."""
    d = (R / "static/js/directory.js").read_text(encoding="utf-8")
    a = (R / "static/js/app.js").read_text(encoding="utf-8")
    assert "function rowAccreditState" in d and "st1 === 'none'" in d and "st0 === 'none'" in d
    i = d.index("if (data.result === 'DUPLICADO') {                         // ya constaba")
    assert "confirmDuplicateRegistration" not in d[i:i + 400]
    j = a.index("if (data.result === 'DUPLICADO') {                   // ya constaba")
    assert "confirmDuplicateRegistration" not in a[j:j + 400]


def test_recuadros_de_resultado_foto_en_editar_y_acreditar_en_el_escaner():
    """23-nov-2026 (pedido de Juan David): ya acreditado = recuadro verde; no se detectó la cara = amarillo (repetir); no está en la base = rojo; Editar muestra la foto de
    registro y pasa a «Retomar»; el panel de comparación del escáner trae «Acreditar a esta persona» (PATCH de estado con método biométrico)."""
    css = (R / "static/css/registro.css").read_text(encoding="utf-8")
    assert "background: var(--gw-ok-bg)" in css and "background: var(--gw-warn-bg)" in css and "background: var(--gw-err-bg)" in css
    a = (R / "static/js/app.js").read_text(encoding="utf-8")
    assert "no_face" in a and "'warn'" in a and "Ya estaba acreditado(a): no se volvió a acreditar', 'ok'" in a
    assert "method: 'biometrico'" in a and "scanAccreditBtn" in (R / "templates/kiosk_registro.html").read_text(encoding="utf-8")
    d = (R / "static/js/directory.js").read_text(encoding="utf-8")
    assert "registration-photo" in d and "Retomar la foto" in d
    api = (R / "app/routers/api.py").read_text(encoding="utf-8")
    assert '"reason": "no_face"' in api and '"reason": "no_match"' in api and "def registration_photo" in api


def test_aceptar_dice_con_claridad_que_la_foto_nueva_quedo_pendiente():
    """23-nov-2026: si la selfie queda pendiente (ya había foto de registro y la persona no está verificada), el mensaje no dice solo «Listo»: dice que la anterior sigue vigente."""
    s = (R / "app/routers/aceptar.py").read_text(encoding="utf-8")
    assert "held = hold" in s and '"photo_held": True' in s and "no reemplaza a la anterior" in s
    assert s.index('"photo_held": True') < s.index('"message": "¡Gracias! Cuando llegues,')


def test_historial_de_fotos_se_conservan_las_dos():
    """23-nov-2026: al verificar a la persona NO se reemplaza la foto de registro: la selfie se conserva como segunda foto, cubierta por toda purga (`photo_keys`), y «Editar» muestra las dos."""
    e = (R / "app/enroll.py").read_text(encoding="utf-8")
    assert "def selfie_photo_key" in e and "selfie_photo_key(tenant_id, user_id))" in e.split("def photo_keys")[1][:500]
    prom = e.split("def promote_pending")[1].split("def status")[0]
    assert "selfie_photo_key(" in prom and "photo_key(tenant_id, str(user_id)))" not in prom.split("st.move(")[1].split("\n")[0]
    assert "which == \"selfie\"" in (R / "app/routers/api.py").read_text(encoding="utf-8")
    d = (R / "static/js/directory.js").read_text(encoding="utf-8")
    assert "editModalSelfiePhoto" in d and "which=${which}" in d


def test_anexo_bloquea_la_camara_y_se_sube_en_parametros():
    """23-nov-2026: modo «acepto» por defecto con fotos del cliente; el archivo del anexo se sube en Parámetros y sin él la cámara queda bloqueada con el motivo."""
    b = (R / "app/biometric_setup.py").read_text(encoding="utf-8")
    assert "def annex_block_reason" in b and "event.facial_enabled and event.client_photos_before and not has_annex(event)" in b and "ANNEX_MISSING" in b
    assert "event.facial_enabled and event.client_photos_before):" in b.split("def apply_precalc_default")[1]          # ya no exige tercero ni anexo para encender el clic
    api, con, par = [(R / f).read_text(encoding="utf-8") for f in ("app/routers/api.py", "app/routers/consents.py", "app/routers/parametros.py")]
    assert "biometric_setup.annex_block_reason(event)" in api.split("def recognize(")[1][:2500]          # el servidor no reconoce sin anexo
    assert "annex_block_reason(event)" in con.split("def consent_click")[1][:900]
    assert "facial-annex" in par and "def upload_facial_annex" in par and "ANNEX_MAX" in par
    tpl = (R / "templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert 'id="annexUpload"' in tpl and "Cámara bloqueada" in tpl and 'id="pcSave"' not in tpl
    assert "FACIAL_ANNEX_BLOCK" in (R / "templates/kiosk_registro.html").read_text(encoding="utf-8") and "FACIAL_ANNEX_BLOCK" in (R / "static/js/app.js").read_text(encoding="utf-8")


def test_tercer_modo_cada_quien_acepta():
    """23-nov-2026: «cada quien acepta» (formulario/QR): escáner sin cédula, con «Acepto»; solo reconoce a quienes ya aceptaron (no es `ungated`) y no exige anexo."""
    b = (R / "app/biometric_setup.py").read_text(encoding="utf-8")
    assert "event.each_accepts and event.facial_enabled" in b.split("def click_mode")[1][:400]
    assert "event.facial_enabled and event.client_photos_before and not has_annex" in b          # el anexo sigue siendo solo de fotos del cliente
    api = (R / "app/routers/api.py").read_text(encoding="utf-8")
    assert "ungated=bool(click) and bool(event.precalculo_autorizado)" in api and "biometric_setup.click_mode(event)" in api
    con = (R / "app/routers/consents.py").read_text(encoding="utf-8")
    assert con.count('"each_accepts"') >= 4 and "Elige una sola fuente de fotos" in con
    assert "each_accepts" in (R / "app/models.py").read_text(encoding="utf-8") and (R / "alembic/versions/0165_each_accepts.py").exists()
    assert 'id="bsEach"' in (R / "templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert len("0165_each_accepts") <= 32


def test_un_solo_selector_de_modo_anexo_visible_y_foto_escarapela_para_coordinador():
    t = (R / "templates/kiosk_parametros.html").read_text(encoding="utf-8")
    assert t.count('name="bsSource"') >= 3 and '<select class="gw-select" id="ccMode"' not in t and 'type="hidden" id="ccMode"' in t          # un solo selector (ya no «responsable» + «origen»)
    assert "¿De dónde salen las fotos de los asistentes?" not in t and "syncSource" in t
    assert 'id="annexBox"' in t and "{% if not local_server %}\n            <div class=\"gw-group__item\" id=\"annexBox\"" in t          # el campo del anexo siempre está en la página
    assert "Opciones solo para el súper administrador" not in t and 'id="badgeBioPhoto"' in t
    c = (R / "app/routers/consents.py").read_text(encoding="utf-8")
    assert "def set_badge_bio_photo(event_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(COORD))" in c
