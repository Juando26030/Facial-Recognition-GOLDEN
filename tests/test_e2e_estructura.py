"""Pruebas de texto (sin navegador, sin app) de la base E2E de tests/e2e. Correr con:
python3 -m pytest --noconftest -q tests/test_e2e_estructura.py"""
import re
from pathlib import Path

E2E = Path("tests/e2e")
WORKFLOW = Path(".github/workflows/e2e-staging.yml")


def _fuentes():
    return {p: p.read_text(encoding="utf-8") for p in E2E.glob("*.py")}


def test_sin_contrasenas_ni_correos_reales():
    for p, txt in _fuentes().items():
        assert not re.search(r"""(password|clave|passwd)\s*=\s*["'][^"']+["']""", txt, re.I), f"{p}: contraseña escrita en el código"
        for correo in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", txt):
            assert correo.endswith(("@example.invalid", "@example.com")), f"{p}: correo que parece real: {correo}"


def test_candado_contra_produccion():
    src = (E2E / "conftest.py").read_text(encoding="utf-8")
    assert "def validar_destino" in src and "app.golden-eventos.com" in src
    assert all(x in src for x in ("staging", "localhost", "127.0.0.1")) and "PROHIBIDO" in src
    assert "validar_destino(os.environ.get(\"E2E_BASE_URL\"" in src, "base_url debe pasar siempre por el candado"


def test_se_salta_en_la_suite_normal():
    src = (E2E / "conftest.py").read_text(encoding="utf-8")
    assert 'if not os.environ.get("E2E_BASE_URL")' in src and 'collect_ignore_glob = ["test_*.py"]' in src


def test_workflow_solo_manual_y_permisos_minimos():
    import yaml
    txt = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(txt)
    disparadores = wf.get("on", wf.get(True))      # YAML 1.1 lee «on» como True
    assert set(disparadores) == {"workflow_dispatch"}
    assert wf["permissions"] == {"contents": "read"}
    for s in ("secrets.E2E_BASE_URL", "secrets.E2E_USER", "secrets.E2E_PASSWORD", "playwright install --with-deps chromium", "upload-artifact"):
        assert s in txt, s
    assert "kiosk-printing" not in txt


def test_sin_kiosk_printing_ni_nube():
    for p, txt in _fuentes().items():
        assert "--kiosk-printing" not in txt and "gcloud" not in txt, p


def test_selectores_existen_en_las_plantillas():
    login = Path("templates/login.html").read_text(encoding="utf-8")
    assert 'id="usuario"' in login and 'id="clave"' in login and 'action="/login"' in login
    reg = Path("templates/kiosk_registro.html").read_text(encoding="utf-8")
    for s in ('id="searchCedula"', 'id="directoryTableBody"', 'id="directorio"', 'scope="col"', "Estado"):
        assert s in reg, s
    assert 'id="skRows"' in Path("templates/configuracion.html").read_text(encoding="utf-8")
    assert "Deshabilitar" in Path("static/js/server-keys-card.js").read_text(encoding="utf-8")
    assert '@router.post("/register")' in Path("app/routers/api.py").read_text(encoding="utf-8")
    assert "kiosk/{event_id}/registro" in Path("app/main.py").read_text(encoding="utf-8")
    pruebas = (E2E / "test_staging.py").read_text(encoding="utf-8")
    for s in ("#usuario", "#clave", "#searchCedula", "#directoryTableBody", "#skRows"):
        assert s in pruebas or s in (E2E / "conftest.py").read_text(encoding="utf-8"), s


def test_leeme_es_honesto():
    t = (E2E / "LEEME.md").read_text(encoding="utf-8")
    assert "sin poder correrlas contra staging" in t and "E2E_BASE_URL" in t
