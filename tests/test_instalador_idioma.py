"""El instalador de Windows debe funcionar igual en Windows en español y en inglés: nada de nombres de cuentas/grupos traducibles ni de texto de comandos."""
import glob
import re
from pathlib import Path

WIN = Path(__file__).resolve().parent.parent / "deploy" / "windows"


def test_no_localized_account_names_in_scripts():
    for p in glob.glob(str(WIN / "*.ps1")):
        text = Path(p).read_text(encoding="utf-8-sig")
        for bad in ("BUILTIN\\Administrators", "BUILTIN\\Users", "NETWORK SERVICE", "Administradores", "Usuarios autenticados"):
            code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
            assert bad not in code, f"{Path(p).name} usa «{bad}» (cambia con el idioma de Windows): usar SID (*S-1-5-…)"


def test_permissions_use_well_known_sids():
    text = (WIN / "install.ps1").read_text(encoding="utf-8-sig")
    for sid in ("*S-1-5-18", "*S-1-5-32-544", "*S-1-5-32-545", "*S-1-5-20"):
        assert sid in text


def test_powershell_scripts_have_bom_so_accents_survive_windows_powershell_5():
    for p in glob.glob(str(WIN / "*.ps1")):
        assert Path(p).read_bytes().startswith(b"\xef\xbb\xbf"), f"{Path(p).name} sin BOM"


def test_installer_offers_spanish_and_english():
    iss = (WIN / "GoldenLocal.iss").read_text(encoding="utf-8")
    assert re.search(r'Name: "spanish"', iss) and re.search(r'Name: "english"', iss)


def test_database_is_created_directly_and_verified():
    text = (WIN / "install.ps1").read_text(encoding="utf-8-sig")
    assert "Invoke-AsNetworkService" not in text
    assert "PG_VERSION" in text and "No se pudo crear la base de datos" in text
