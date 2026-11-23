"""Editar persona ofrece «Captar rostro» (solo con reconocimiento facial) y usa el mismo camino con aceptación de la persona."""
from pathlib import Path

R = Path(__file__).resolve().parent.parent


def test_boton_en_editar_y_camino_unico():
    d = (R / "static/js/directory.js").read_text(encoding="utf-8")
    a = (R / "static/js/app.js").read_text(encoding="utf-8")
    assert "editModalFace" in d and "window.GoldenFace" in d          # el botón solo existe si el escáner facial está en la página
    assert "window.GoldenFace = {" in a and "identify()" in a          # reutiliza identify(): la aceptación de la persona sigue siendo obligatoria
    assert "enroll-face" in a                                          # y la foto se guarda por el endpoint que exige aceptación
