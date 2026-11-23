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
