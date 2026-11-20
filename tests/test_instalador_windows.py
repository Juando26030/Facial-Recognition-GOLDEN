"""Fase 6: lo programable del instalador de Windows (deploy/windows/). Los scripts de PowerShell y el instalador NO se pueden ejecutar aquí (no hay Windows): se prueba lo que sí —
el filtro de dependencias, los certificados y que las piezas coincidan entre sí (nombres de servicios, puerto, variables que lee la app)."""
import importlib.util
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent
WIN = SRC / "deploy" / "windows"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, WIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_local_requirements_drop_face_stack_and_gunicorn():
    mk = _load("make_requirements")
    out = mk.filter_lines((SRC / "requirements.txt").read_text(encoding="utf-8").splitlines(keepends=True))
    names = {re.split(r"[\s=<>!~;@\[]", ln.strip(), maxsplit=1)[0].lower() for ln in out if ln.strip() and not ln.strip().startswith("#")}
    assert not names & {"dlib", "face_recognition", "face_recognition_models", "gunicorn"}
    assert {"fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg2-binary", "cryptography"} <= names          # lo que la app «web» sí necesita
    assert mk.filter_lines(["dlib==20.0.1\n", "# dlib no\n", "numpy==2.0\n"]) == ["# dlib no", "numpy==2.0"]


def test_certificates_have_the_local_names_and_ips_and_verify(tmp_path):
    gen = _load("gen_cert")
    info = gen.make(tmp_path, "PORTATIL1", ["192.168.1.10", "no-es-ip"])
    assert {"PORTATIL1", "golden.local", "localhost", "127.0.0.1", "192.168.1.10"} <= set(info["names"])
    assert gen.days_left(tmp_path / "server.pem") >= 800
    assert (tmp_path / "GoldenLocal-CA.cer").stat().st_size > 100 and (tmp_path / "server.key").exists()
    ca_before = (tmp_path / "ca.pem").read_bytes()
    gen.make(tmp_path, "PORTATIL1", [])                                                                  # renovar el certificado NO cambia la autoridad (los celulares no repiten la instalación)
    assert (tmp_path / "ca.pem").read_bytes() == ca_before


def test_pieces_agree_on_names_port_and_paths():
    cfg = (WIN / "config.ps1").read_text(encoding="utf-8")
    port = re.search(r"\$AppPort\s*=\s*(\d+)", cfg).group(1)
    for svc in ("GoldenLocalApp", "GoldenLocalUpdater", "GoldenLocalDB"):
        assert f"'{svc}'" in cfg
    for xml, sid in (("GoldenLocalApp.xml", "GoldenLocalApp"), ("GoldenLocalUpdater.xml", "GoldenLocalUpdater")):
        text = (WIN / xml).read_text(encoding="utf-8")
        assert f"<id>{sid}</id>" in text and "C:\\GoldenLocal\\scripts" in text
    iss = (WIN / "GoldenLocal.iss").read_text(encoding="utf-8")
    assert f"localhost:{port}" in iss and "install.ps1" in iss and "uninstall.ps1" in iss and "PrivilegesRequired=admin" in iss
    assert "uninsneveruninstall" in iss                                                                  # la desinstalación no borra datos, base ni copias
    inst = (WIN / "install.ps1").read_text(encoding="utf-8")
    for needle in ("LOCAL_SERVER", "LOCAL_UPDATE_DIR", "PRODUCTION_URL", "power.ps1", "alembic upgrade head", "-RemoteAddress LocalSubnet"):
        assert needle in inst, needle
    upd = (WIN / "run-update.ps1").read_text(encoding="utf-8")
    for needle in ("Backup-Database", "Get-FileHash", "alembic upgrade head", "rolledback", "pg_restore", "StartsWith('https://')"):
        assert needle in upd, needle
    assert "standby-timeout-ac 0" in (WIN / "power.ps1").read_text(encoding="utf-8")


def test_status_states_written_by_the_updater_are_known_to_the_app():
    from app import local_update
    upd = (WIN / "run-update.ps1").read_text(encoding="utf-8") + (WIN / "config.ps1").read_text(encoding="utf-8")
    written = set(re.findall(r"Write-UpdateStatus\s+'(\w+)'", upd))
    assert written and written <= set(local_update.STATES), written - set(local_update.STATES)


def test_workflow_is_manual_only_and_does_not_publish():
    wf = (SRC / ".github" / "workflows" / "instalador-windows.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf and "push:" not in wf and "pull_request" not in wf and "schedule" not in wf


def test_instalador_cierra_procesos_antes_de_reinstalar():
    """Reinstalar encima con el servicio corriendo falló con «código 5» (postgres.exe mantenía icudt77.dll): el instalador debe parar servicios y procesos de la carpeta."""
    iss = (WIN / "GoldenLocal.iss").read_text(encoding="utf-8")
    for svc in ("GoldenLocalUpdater", "GoldenLocalApp", "GoldenLocalDB"):
        assert f"stop {svc}" in iss
    assert "Stop-Process -Force" in iss and "StartsWith($d" in iss


def test_instalador_avisa_si_pisa_una_version_mas_nueva():
    """El instalador compara su hora de construcción con el .build_info instalado y pide confirmar antes de sobrescribir algo más nuevo (silencioso: se niega)."""
    iss = (WIN / "GoldenLocal.iss").read_text(encoding="utf-8")
    assert "function InitializeSetup" in iss and "#define BuildStamp" in iss and ".build_info" in iss
    assert "Inst > Mine" in iss and "WizardSilent" in iss and "MB_DEFBUTTON2" in iss
    sh = (WIN / "build_en_cloudshell.sh").read_text(encoding="utf-8")
    assert "GOLDEN_BUILD_STAMP" in sh and "date -u +%Y%m%d%H%M%S" in sh


def test_build_cross_pide_tzdata_explicito():
    """pandas necesita tzdata en Windows; instalado desde Linux el marcador lo omite: debe pedirse a mano o el instalador falla en pip."""
    txt = (SRC / "deploy" / "windows" / "build_cross.py").read_text(encoding="utf-8")
    assert 'req.append("tzdata")' in txt
