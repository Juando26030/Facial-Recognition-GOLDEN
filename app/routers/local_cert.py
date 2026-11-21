"""Quitar el aviso «No seguro» en los equipos que se conectan al servidor local (20-nov-2026).

El servidor local firma su HTTPS con su propia autoridad («Golden Local CA», deploy/windows/gen_cert.py). El navegador del servidor ya confía en ella (la instala el instalador),
pero cada computador o celular que se conecta por la red local muestra «No seguro» hasta que la instala UNA vez. No hay forma de evitarlo desde el servidor sin un certificado
público (que exige un dominio e internet, descartado en docs/17 §2). Aquí se entrega lo necesario para instalarla en un paso:

  GET /certificado                         página con instrucciones por dispositivo (Windows, Android, iPhone/iPad, Mac)
  GET /certificado/golden-local-ca.cer     la autoridad (DER) para celulares y Mac
  GET /certificado/instalar-windows.cmd    doble clic en Windows: la instala para el usuario (sin permisos de administrador; Windows pide confirmar)

Solo en servidores locales (LOCAL_SERVER=1); en la nube responden 404. Sin sesión (la autoridad es pública: solo sirve para comprobar, no para firmar; la llave privada nunca sale)
y sin base de datos. La carpeta es LOCAL_CERT_DIR (la escribe install.ps1) o C:\\GoldenLocal\\certs. Es configuración del equipo, no datos: no pasa por app/storage.py.
"""
import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import localmode

router = APIRouter()
DEFAULT_DIR = r"C:\GoldenLocal\certs"
CA_FILE = "GoldenLocal-CA.cer"


def cert_dir() -> Path:
    return Path((os.getenv("LOCAL_CERT_DIR") or "").strip() or DEFAULT_DIR)


def ca_der() -> Optional[bytes]:
    """La autoridad en DER (el .cer que deja gen_cert.py), o None si no existe."""
    p = cert_dir() / CA_FILE
    try:
        data = p.read_bytes()
    except OSError:
        return None
    return data or None


def fingerprint(der: bytes) -> str:
    """Huella SHA-256 como la muestran Windows y los celulares (AA:BB:…): sirve para comprobar que es la de ESTE servidor."""
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def windows_cmd(der: bytes) -> str:
    """Script de doble clic para Windows: escribe la autoridad en un archivo temporal y la agrega a las autoridades de confianza DEL USUARIO (certutil -user, sin administrador;
    Windows muestra su aviso de seguridad y hay que aceptar). Chrome y Edge usan ese almacén. Fin de línea CRLF (cmd.exe)."""
    b64 = base64.b64encode(der).decode("ascii")
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    out = ["@echo off", "chcp 65001 >nul",
           "echo.", "echo   Golden Local: instalar el certificado de este servidor", "echo   (quita el aviso «No seguro» del navegador en ESTE computador)", "echo.",
           'set "GLD_CER=%TEMP%\\golden-local-ca.cer"',
           "(", "echo -----BEGIN CERTIFICATE-----"] + ["echo " + ln for ln in lines] + ["echo -----END CERTIFICATE-----", ') > "%GLD_CER%"',
           "echo   Windows va a mostrar un aviso de seguridad: elige «Sí» para instalarlo.", "echo.",
           'certutil -user -addstore Root "%GLD_CER%"',
           "if errorlevel 1 (",
           "  echo.", "  echo   No se instalo. Vuelve a intentarlo y elige «Si» en el aviso de Windows.",
           ") else (",
           "  echo.", "  echo   Listo. Cierra TODAS las ventanas del navegador y vuelve a abrir la direccion del servidor.",
           ")",
           'del "%GLD_CER%" >nul 2>&1',
           "echo.", "pause"]
    return "\r\n".join(out) + "\r\n"


def _require_local() -> None:
    if not localmode.is_local_server():
        raise HTTPException(status_code=404, detail="No encontrado")


@router.get("/certificado")
def certificate_page(request: Request):
    _require_local()
    from app.main import templates
    der = ca_der()
    host = (request.headers.get("host") or "").strip()
    return templates.TemplateResponse(request=request, name="certificado_local.html",
                                      context={"available": der is not None, "fingerprint": fingerprint(der) if der else "", "server_url": f"https://{host}" if host else ""})


@router.get("/certificado/golden-local-ca.cer")
def certificate_file():
    _require_local()
    der = ca_der()
    if der is None:
        raise HTTPException(status_code=404, detail="Este servidor todavía no tiene certificado.")
    return Response(content=der, media_type="application/x-x509-ca-cert", headers={"Content-Disposition": 'attachment; filename="golden-local-ca.cer"', "Cache-Control": "no-store"})


@router.get("/certificado/instalar-windows.cmd")
def certificate_windows():
    _require_local()
    der = ca_der()
    if der is None:
        raise HTTPException(status_code=404, detail="Este servidor todavía no tiene certificado.")
    return Response(content=windows_cmd(der).encode("utf-8"), media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="Instalar-certificado-Golden-Local.cmd"', "Cache-Control": "no-store"})
