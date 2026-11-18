"""Prepara el contenido del instalador de Windows DESDE LINUX (Cloud Shell / Docker), sin necesitar un computador Windows. Hace lo mismo que build_installer.ps1 (pasos 1 a 5):
la app, el paquete de actualización, Python embebido de Windows con sus dependencias (ruedas win_amd64 bajadas desde aquí), PostgreSQL de Windows y WinSW. El paso 6 (compilar el
instalador con Inno Setup) lo hace build_en_cloudshell.sh con Wine. Uso (dentro de python:3.13): python deploy/windows/build_cross.py <versión> <commit>"""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

PY_VER, PG_VER, WINSW_VER = "3.13.1", "18.0-1", "v2.12.0"
REPO = pathlib.Path(__file__).resolve().parents[2]
BUILD = REPO / "build" / "windows"
PAYLOAD, CACHE, OUT = BUILD / "payload", BUILD / "cache", BUILD / "out"


def fetch(url: str, dest: pathlib.Path) -> pathlib.Path:
    if not dest.exists():
        print("Descargando", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "golden-build"})
        with urllib.request.urlopen(req) as r, open(dest, "wb") as fh:
            shutil.copyfileobj(r, fh)
    print("  huella de %s: %s" % (dest.name, hashlib.sha256(dest.read_bytes()).hexdigest()), flush=True)
    return dest


def run(*cmd):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main(version: str, commit: str) -> None:
    shutil.rmtree(PAYLOAD, ignore_errors=True)
    for d in (PAYLOAD, CACHE, OUT):
        d.mkdir(parents=True, exist_ok=True)
    # 1. La aplicación (solo lo que corre)
    app = PAYLOAD / "app"
    app.mkdir()
    for item in ("app", "alembic", "static", "templates"):
        shutil.copytree(REPO / item, app / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(REPO / "alembic.ini", app / "alembic.ini")
    sys.path.insert(0, str(REPO / "deploy" / "windows"))
    from make_requirements import filter_lines
    req = filter_lines((REPO / "requirements.txt").read_text(encoding="utf-8").splitlines(True))
    (app / "requirements-local.txt").write_text("\n".join(req) + "\n", encoding="utf-8", newline="\n")
    (app / ".build_info").write_text(json.dumps({"commit": commit, "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, separators=(",", ":")), encoding="utf-8")
    # 2. Paquete de actualización = la carpeta app\ comprimida
    zip_path = OUT / ("golden-local-update-%s.zip" % version)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app).as_posix())
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (OUT / ("golden-local-update-%s.sha256" % version)).write_text("%s  %s\n" % (sha, zip_path.name), encoding="ascii")
    # 3. Python embebido de Windows + pip + dependencias (ruedas de Windows)
    py_zip = fetch("https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip" % (PY_VER, PY_VER), CACHE / ("python-%s-embed-amd64.zip" % PY_VER))
    py = PAYLOAD / "python"
    with zipfile.ZipFile(py_zip) as z:
        z.extractall(py)
    pth = next(py.glob("python*._pth"))
    lines = [("import site" if re.match(r"^#\s*import site", ln) else ln) for ln in pth.read_text().splitlines()]
    lines += ["Lib\\site-packages", "..\\app"]
    pth.write_text("\n".join(lines) + "\n", encoding="ascii")
    site = py / "Lib" / "site-packages"
    site.mkdir(parents=True)
    run(sys.executable, "-m", "pip", "install", "--target", site, "--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313",
        "--only-binary=:all:", "--disable-pip-version-check", "--no-warn-script-location", "pip", "-r", app / "requirements-local.txt")
    # 4. PostgreSQL (binarios de EDB, solo lo necesario)
    pg_zip = fetch("https://get.enterprisedb.com/postgresql/postgresql-%s-windows-x64-binaries.zip" % PG_VER, CACHE / ("postgresql-%s-windows-x64-binaries.zip" % PG_VER))
    tmp = CACHE / "pg-extract"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(pg_zip) as z:
        z.extractall(tmp)
    shutil.move(str(tmp / "pgsql"), str(PAYLOAD / "pgsql"))
    for junk in ("doc", "pgAdmin 4", "StackBuilder", "symbols", "include"):
        shutil.rmtree(PAYLOAD / "pgsql" / junk, ignore_errors=True)
    # 5. WinSW (servicios de Windows)
    tools = PAYLOAD / "tools"
    tools.mkdir()
    ws = fetch("https://github.com/winsw/winsw/releases/download/%s/WinSW-x64.exe" % WINSW_VER, CACHE / ("WinSW-%s.exe" % WINSW_VER))
    shutil.copy2(ws, tools / "WinSW.exe")
    # 6. Componente Visual C++ 2015-2022 x64 (lo necesita PostgreSQL; prereq.ps1 lo instala sin internet si el equipo no lo tiene)
    vc = fetch("https://aka.ms/vs/17/release/vc_redist.x64.exe", CACHE / "vc_redist.x64.exe")
    shutil.copy2(vc, tools / "vc_redist.x64.exe")
    print("\nContenido listo en", PAYLOAD, "| huella del paquete de actualización:", sha)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
