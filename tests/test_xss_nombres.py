"""C1/C2 (Fase 3): los nombres de color y de plantilla guardada no admiten «<» ni «>» y la plantilla tiene tope de 80 caracteres.
Las dos primeras no usan base; las demás usan el Postgres de pruebas."""
import pytest

from tests.conftest import login


def test_save_as_in_rejects_markup_and_long_names_without_database():
    pydantic = pytest.importorskip("pydantic")
    from app.routers.badges import SaveAsIn
    assert SaveAsIn(name="Feria 2026").name == "Feria 2026"
    for bad in ("<script>", "<img src=x onerror=1>", "a>b", "", "x" * 81):
        with pytest.raises(pydantic.ValidationError):
            SaveAsIn(name=bad)
    assert SaveAsIn(name="x" * 80)


def test_check_text_is_what_save_color_uses():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "app/routers/events.py").read_text(encoding="utf-8")
    chunk = src[src.index("def save_color("):src.index("def _color_or_404")]
    assert 'check_text(name, "El nombre del color")' in chunk and chunk.index("check_text") < chunk.index("SavedColor(")


def test_colors_api_rejects_markup_in_name(client, factory):
    factory.staff("coordinador", "coo")
    login(client, "coo")
    for bad in ("<img src=x onerror=1>", "a>b"):
        r = client.post("/api/colors", json={"name": bad, "hex": "#112233"})
        assert r.status_code == 400 and "«<»" in r.json()["detail"]
    assert client.post("/api/colors", json={"name": "Rojo Golden", "hex": "#112233"}).status_code == 200


def test_badge_template_save_as_rejects_markup_and_long_names(client, factory):
    factory.staff("coordinador", "coo")
    ev = factory.event()
    login(client, "coo")
    url = f"/api/events/{ev.id}/badge-template/save-as"
    assert client.post(url, json={"name": "<script>"}).status_code == 422
    assert client.post(url, json={"name": "x" * 81}).status_code == 422
