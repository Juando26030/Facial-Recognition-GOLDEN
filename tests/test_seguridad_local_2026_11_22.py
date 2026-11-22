"""Revisión de seguridad del servidor local (22-nov-2026, docs/revision_2026-11-22/04_seguridad_servidor_local.md). Sin Windows ni base: texto de los scripts y lógica pura."""
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent
WIN = SRC / "deploy" / "windows"


def _read(name: str) -> str:
    return (WIN / name).read_text(encoding="utf-8-sig")


def test_updater_downloads_the_package_without_following_redirects():
    """El token del servidor (X-Node-Token) solo viaja a producción: ni el manifiesto ni la DESCARGA del paquete siguen una redirección (igual que download-app.ps1)."""
    src = _read("run-update.ps1")
    line = next(ln for ln in src.splitlines() if "Invoke-WebRequest -Uri $pkgUrl" in ln)
    assert "-MaximumRedirection 0" in line
    dl = next(ln for ln in _read("download-app.ps1").splitlines() if "Invoke-WebRequest -Uri $pkgUrl" in ln)
    assert "-MaximumRedirection 0" in dl


def test_wipe_script_exists_and_is_deliberate():
    """Devolución del portátil: hay un script que borra base, archivos, copias, secretos y llaves, exige escribir BORRAR, detiene los servicios y retira la autoridad de Windows."""
    src = _read("borrar-datos.ps1")
    assert ". \"$PSScriptRoot\\config.ps1\"" in src
    assert "-cne 'BORRAR'" in src                                   # confirmación explícita (salvo -Yes para uso guiado)
    assert "Stop-Service $svc" in src and "$SvcUpd, $SvcApp, $SvcPg" in src
    for target in ("$PgData", "$FilesDir", "$BackupDir", "$EnvFile", "$CertDir"):
        assert target in src
    assert "Cert:\\LocalMachine\\Root" in src and "Golden Local CA" in src
    assert "cipher.exe /w:" in src                                  # sobrescritura del espacio libre (opcional)
    assert "Pasar a internet" in src                                # recuerda subir todo antes de borrar
    # El instalador copia todos los .ps1 a scripts\: el de borrado viaja con él sin tocar el .iss
    assert 'Source: "*.ps1"; DestDir: "{app}\\scripts"' in _read("GoldenLocal.iss")


def test_uninstall_keeps_data_and_points_to_the_wipe_script():
    src = _read("uninstall.ps1")
    assert "NO borra la base de datos" in src and "borrar-datos.ps1" in src


def test_docs_explain_loss_protocol_and_return_of_the_laptop():
    doc = (SRC / "docs" / "17_SERVIDOR_LOCAL.md").read_text(encoding="utf-8")
    assert "borrar-datos.ps1" in doc and "BitLocker" in doc
    assert "pérdida o robo" in doc.lower() or "pérdida o robo" in doc
    assert "04_seguridad_servidor_local.md" in doc
