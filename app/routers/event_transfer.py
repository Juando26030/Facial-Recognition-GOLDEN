"""Exportar / importar un evento COMPLETO entre entornos (docs/18_EXPORTAR_EVENTOS.md). Solo super_admin. El motor vive en app/event_transfer.py y el trabajo en segundo plano en
app/event_transfer_jobs.py (el mismo motor lo usan los scripts de línea de comandos). Flujo de la interfaz:

  Exportar:  POST /event-transfer/export/start → GET /event-transfer/jobs/{n} (avance) → GET /event-transfer/download/{n}?t=<URL firmada de 5 min> (el .zip se borra a las 24 h).
  Importar:  POST /event-transfer/upload-url (subida directa) → POST /event-transfer/import/inspect → POST /event-transfer/import/start (dry_run=true: simulacro; false: de verdad)
             → GET /event-transfer/jobs/{n} → POST /event-transfer/imports/{import_id}/confirm (si el evento quedó en espera).
Los endpoints de un solo paso de la fase F1 (export/{id}, import/dry-run, import) siguen para scripts y pruebas."""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import event_transfer, event_transfer_jobs, uploads
from app import event_lease
from app.auth import assert_event_tenant, get_current_staff, require_role, require_role_or_any
from app.database import get_db
from app.models import Event, EventTransferLog, StaffUser, Tenant
from app.storage import get_storage

log = logging.getLogger("golden.event_transfer")
router = APIRouter()
SUPER = require_role("super_admin")
EXPORTER = require_role_or_any("coordinador", event_lease.LEASE_ROLES)      # Fase 6: bajar un evento a un servidor local lo puede hacer cualquiera de la empresa (menos digitadores y clientes), sobre cualquier evento


def _is_local_server() -> bool:
    import os
    return (os.getenv("LOCAL_SERVER") or "").strip().lower() in ("1", "true", "yes", "si")


def IMPORTER(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    """Importar: en la NUBE solo el super_admin (puede mezclar un evento con los de producción); en un SERVIDOR LOCAL (LOCAL_SERVER=1) los mismos roles que pueden bajar el evento."""
    if _is_local_server():
        return EXPORTER(staff)
    return SUPER(staff)
DOWNLOAD_SECONDS = 5 * 60                      # vida de la URL de descarga


def _fail(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


def _signer() -> URLSafeTimedSerializer:
    import os
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production", salt="event-transfer-download")


# ------------------------------------------------------------------------------------------------ exportar
class ExportStart(BaseModel):
    event_id: int
    include_biometrics: bool = False
    passphrase: Optional[str] = Field(None, max_length=200)


@router.post("/event-transfer/export/start")
def export_start(body: ExportStart, staff: StaffUser = Depends(EXPORTER), db: Session = Depends(get_db)):
    event = db.get(Event, body.event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    try:
        job_id = event_transfer_jobs.start_export(db, staff, event, include_biometrics=body.include_biometrics, passphrase=body.passphrase)
    except event_transfer.TransferError as e:
        raise _fail(e)
    return _job(db, job_id, staff)


def _job(db: Session, job_id: int, staff: StaffUser) -> dict:
    st = event_transfer_jobs.status(db, job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    if st["ready"]:
        st["download_url"] = f"/api/event-transfer/download/{job_id}?t={_signer().dumps({'j': job_id, 'u': staff.id})}"
    return st


@router.get("/event-transfer/jobs/{job_id}")
def job_status(job_id: int, staff: StaffUser = Depends(EXPORTER), db: Session = Depends(get_db)):
    return _job(db, job_id, staff)


@router.get("/event-transfer/download/{job_id}")
def download(job_id: int, t: str, staff: StaffUser = Depends(EXPORTER), db: Session = Depends(get_db)):
    try:
        data = _signer().loads(t, max_age=DOWNLOAD_SECONDS)
    except SignatureExpired:
        raise HTTPException(status_code=410, detail="El enlace de descarga venció: vuelve a pedirlo.")
    except BadSignature:
        raise HTTPException(status_code=400, detail="Enlace de descarga no válido.")
    if data.get("j") != job_id or data.get("u") != staff.id:
        raise HTTPException(status_code=403, detail="Ese enlace no es para tu sesión.")
    row = db.get(EventTransferLog, job_id)
    if not row or row.kind != "job_export" or not row.file_key or not get_storage().exists(row.file_key):
        raise HTTPException(status_code=404, detail="El paquete ya no está disponible (se borra a las 24 horas): expórtalo de nuevo.")
    log.info("event_transfer_download job=%s", job_id)                        # sin datos personales
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", row.event_code or "evento")
    return get_storage().response(row.file_key, filename=f"evento_{name}.zip", media_type="application/zip", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------------------------------------ importar
class UploadReq(BaseModel):
    filename: str = Field(..., max_length=200)
    size: int


@router.post("/event-transfer/upload-url")
def upload_url(body: UploadReq, staff: StaffUser = Depends(IMPORTER)):
    """Subida directa del paquete (URL firmada al almacenamiento; en local, un PUT firmado a la app): el paquete puede ser grande y no pasa por la petición."""
    return uploads.create("event_package", event_transfer_jobs.package_scope(staff), "transfer", body.filename, body.size, "application/zip")


SMALL_UPLOAD = 24 * 1024 * 1024          # por debajo de esto el paquete sube POR la aplicación (Cloud Run admite 32 MB por petición): no depende del CORS del bucket


@router.post("/event-transfer/upload")
def upload_small(file: UploadFile = File(...), staff: StaffUser = Depends(IMPORTER)):
    """Subida de un paquete CHICO por la propia aplicación (sin tocar el bucket desde el navegador, así no hace falta CORS). Los grandes usan `upload-url` (subida directa)."""
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="El paquete debe ser un archivo .zip.")
    data = file.file.read(SMALL_UPLOAD + 1)
    if not data:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(data) > SMALL_UPLOAD:
        raise HTTPException(status_code=400, detail="El paquete pesa más de 24 MB: se sube directo al almacenamiento.")
    return {"token": uploads.stash("event_package", event_transfer_jobs.package_scope(staff), "transfer", file.filename, data, "application/zip")}


class TokenReq(BaseModel):
    token: str


@router.post("/event-transfer/import/inspect")
def import_inspect(body: TokenReq, staff: StaffUser = Depends(IMPORTER)):
    try:
        return event_transfer_jobs.inspect(body.token, staff)
    except event_transfer.TransferError as e:
        raise _fail(e)


class ImportStart(BaseModel):
    token: str
    dry_run: bool = True
    new_event_code: Optional[str] = Field(None, max_length=80)
    new_name: Optional[str] = Field(None, max_length=200)
    target_tenant_id: Optional[str] = Field(None, max_length=80)
    keep_original_state: bool = False
    import_biometrics: bool = True
    passphrase: Optional[str] = Field(None, max_length=200)


@router.post("/event-transfer/import/start")
def import_start(body: ImportStart, staff: StaffUser = Depends(IMPORTER), db: Session = Depends(get_db)):
    if body.target_tenant_id and not db.get(Tenant, body.target_tenant_id):
        raise HTTPException(status_code=400, detail="El cliente elegido no existe en este sistema.")
    job_id = event_transfer_jobs.start_import(db, staff, token=body.token, dry_run=body.dry_run, new_event_code=(body.new_event_code or "").strip() or None,
                                              new_name=(body.new_name or "").strip() or None, target_tenant_id=body.target_tenant_id or None,
                                              keep_original_state=body.keep_original_state, import_biometrics=body.import_biometrics, passphrase=body.passphrase)
    return _job(db, job_id, staff)


@router.post("/event-transfer/imports/{import_id}/confirm")
def confirm_import(import_id: int, staff: StaffUser = Depends(IMPORTER), db: Session = Depends(get_db)):
    try:
        return event_transfer.confirm_import(db, import_id, staff.username)
    except event_transfer.TransferError as e:
        raise _fail(e)


@router.get("/event-transfer/log")
def transfer_log(staff: StaffUser = Depends(SUPER), db: Session = Depends(get_db)):
    """Bitácora de exportaciones e importaciones: quién, cuándo, qué evento y cuántas filas. Sin datos personales."""
    return event_transfer_jobs.history(db)


# ------------------------------------------------------------------------------------------------ un solo paso (fase F1: scripts y pruebas)
@router.get("/event-transfer/export/{event_id}")
def export_event(event_id: int, include_biometrics: bool = False, staff: StaffUser = Depends(EXPORTER), db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    assert_event_tenant(event, staff)
    if include_biometrics:
        raise HTTPException(status_code=400, detail="La biometría se exporta desde el asistente (pide una frase de transporte): usa «Exportar evento».")
    data, _ = event_transfer.export_event(db, event, staff_username=staff.username)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", event.event_code or "evento")
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="evento_{name}.zip"', "Cache-Control": "no-store"})


def _run(file: UploadFile, new_event_code: Optional[str], new_name: Optional[str], keep_original_state: bool, dry_run: bool, staff: StaffUser, db: Session) -> dict:
    data = file.file.read()
    try:
        return event_transfer.import_package(db, data, staff_username=staff.username, new_event_code=(new_event_code or "").strip() or None,
                                             new_name=(new_name or "").strip() or None, keep_original_state=keep_original_state, dry_run=dry_run)
    except event_transfer.TransferError as e:
        raise _fail(e)


@router.post("/event-transfer/import/dry-run")
def import_dry_run(file: UploadFile = File(...), new_event_code: Optional[str] = Form(None), new_name: Optional[str] = Form(None), keep_original_state: bool = Form(False),
                   staff: StaffUser = Depends(IMPORTER), db: Session = Depends(get_db)):
    return _run(file, new_event_code, new_name, keep_original_state, True, staff, db)


@router.post("/event-transfer/import")
def import_event(file: UploadFile = File(...), new_event_code: Optional[str] = Form(None), new_name: Optional[str] = Form(None), keep_original_state: bool = Form(False),
                 staff: StaffUser = Depends(IMPORTER), db: Session = Depends(get_db)):
    report = _run(file, new_event_code, new_name, keep_original_state, False, staff, db)
    if not report.get("ok"):
        raise HTTPException(status_code=409, detail={"message": "No se importó nada: hay conflictos.", "conflicts": report["conflicts"]})
    return report
