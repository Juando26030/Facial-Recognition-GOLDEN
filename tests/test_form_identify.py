"""P5: paso de identificación (cédula) editable — título, texto con formato, imagen y botón; vacío = lo de siempre."""
import pytest

from app import formlib as fl
from app.routers import form_transfer
from tests.conftest import login
from tests.test_forms import _create, _event, _open, _put, _state


def test_defaults_are_empty_so_the_old_texts_are_used():
    assert fl.DEFAULT_SETTINGS["identify"] == {"title": "", "text": "", "image": "", "button": ""}
    assert fl.sanitize_settings({})["identify"] == {"title": "", "text": "", "image": "", "button": ""}


def test_identify_is_sanitized():
    got = fl.sanitize_settings({"identify": {"title": "Bienvenido", "button": "Entrar", "image": "acme/x.png", "text": "<b>Hola</b><script>alert(1)</script><img src=x onerror=alert(1)>"}})["identify"]
    assert got == {"title": "Bienvenido", "text": "<b>Hola</b>", "image": "acme/x.png", "button": "Entrar"}
    assert fl.sanitize_settings({"identify": {"text": "menores de <18 años"}})["identify"]["text"] == "menores de <18 años"
    assert fl.sanitize_settings({"identify": {"title": "<b>t</b>" * 100}})["identify"]["title"].count("<b>") <= 200      # el título es texto plano y con tope
    assert len(fl.sanitize_settings({"identify": {"title": "x" * 999}})["identify"]["title"]) == 200


def test_identify_roundtrips_for_export_import():
    s = fl.sanitize_settings({"identify": {"title": "T", "text": "<i>x</i>", "image": "acme/a.png", "button": "Ok"}})
    assert fl.sanitize_settings(s)["identify"] == s["identify"]
    assert (s["identify"], "image") in list(form_transfer._image_refs({"theme": {}, "fields": {}}, s))      # su imagen viaja en el zip


def test_old_settings_without_identify_still_load():
    from types import SimpleNamespace

    from app import formsvc
    form = SimpleNamespace(settings_json='{"thanks": {"mode": "template", "title": "a", "text": "b", "image": "", "url": ""}}')
    assert formsvc.get_settings(form)["identify"] == {"title": "", "text": "", "image": "", "button": ""}


def test_public_state_carries_the_identify_texts(client, factory):
    ev = _event(client, factory)
    factory.person(ev, "1001", "Ana", "Mora")
    f = _create(client, ev)
    _put(client, ev, f, settings={"security": {"enabled": True, "type": "cedula"}, "prefill": {"mode": "cedula", "source": "event"}})
    _open(client, ev, f)
    assert _state(client, ev, f)["identify"] == {"title": "", "text": "", "image": "", "button": ""}          # formularios que nadie editó: vacío = los textos de siempre
    login(client, "coord1")                                                                   # _open cierra la sesión del cliente: se vuelve a entrar para editar
    assert _put(client, ev, f, settings={"security": {"enabled": True, "type": "cedula"}, "prefill": {"mode": "cedula", "source": "event"},
                                         "identify": {"title": "Hola", "text": "<b>x</b><script>1</script>", "button": "Entrar", "image": ""}}).status_code == 200
    st = _state(client, ev, f)
    assert st["stage"] == "identify" and st["identify"]["title"] == "Hola" and st["identify"]["text"] == "<b>x</b>" and st["identify"]["button"] == "Entrar"


@pytest.mark.parametrize("path", ["javascript:alert(1)", "../x.png", "a/../x.png", "//evil.com/x.png", "https://evil.com/x.png", "a/b.svg", "a/b.png?x=1", "a/b.html", "a\b.png", "x.png", ".hidden/x.png"])
def test_identify_image_must_be_an_uploaded_image_path(path):
    assert fl.sanitize_settings({"identify": {"image": path}})["identify"]["image"] == ""


def test_identify_image_valid_paths_are_kept():
    for ok in ("acme/0123456789abcdef.png", "acme/photo.JPEG".lower(), "acme_2/x-1.webp"):
        assert fl.sanitize_settings({"identify": {"image": ok}})["identify"]["image"] == ok


@pytest.mark.parametrize("bad", [None, "x", 5, []])
def test_garbage_identify_does_not_break(bad):
    assert fl.sanitize_settings({"identify": bad})["identify"] == {"title": "", "text": "", "image": "", "button": ""}
