"""Panel de gastos — pestaña «Infraestructura» (Fase 9C). TODO es solo admin y super_admin (y, desde la Fase 10 B, contabilidad).

  GET    /api/gastos/infra/status                            qué está conectado y qué falta (siempre responde)
  POST   /api/gastos/infra/import/csv                        cargar gastos desde un archivo CSV (alternativa manual)
  GET    /api/gastos/infra/summary?from=AAAA-MM&to=AAAA-MM   gráficos, tabla por evento, fórmula y parámetros
  GET    /api/gastos/infra/costs?from=&to=                    gastos registrados
  POST   /api/gastos/infra/costs                              registrar un gasto manual
  PUT    /api/gastos/infra/costs/{id}   ·   DELETE …/{id}
  POST   /api/gastos/infra/costs/{id}/attachment (PDF/PNG/JPG, ≤5 MB)   ·   GET …/attachment   ·   DELETE …/attachment
  PUT    /api/gastos/infra/settings                           criterio de reparto y TRM por defecto
  POST   /api/gastos/infra/import/google                      importar a mano de la exportación de Google (también corre sola en el Job de ops)
  GET    /api/gastos/infra/neon-usage?month=                  uso de Neon (informativo)
  GET    /api/gastos/infra/export.xlsx?from=&to=
La pestaña «Eventos» vive en app/routers/gastos_eventos.py (otra pieza): no se toca aquí. Nada de datos personales."""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import infra_costs as ic
from app.auth import require_platform_role_or_any
from app.database import get_db
from app.models import AuditAction, InfraCost, StaffUser
from app.storage import get_storage
from app.timeutil import utcnow

log = logging.getLogger("golden.gastos")
router = APIRouter()
ADMIN = require_platform_role_or_any("admin", ("contabilidad",))          # admin y super_admin GLOBALES (F5-9 E) y, desde la Fase 10 B, contabilidad (principal o sumado): registra y consulta los gastos
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _audit(db: Session, staff: StaffUser, action: str, c: Optional[InfraCost], detail: str = "") -> None:
    """Quién tocó qué gasto. El detalle lleva proveedor/mes, jamás el nombre del archivo adjunto ni notas."""
    db.add(AuditAction(actor_id=staff.id, actor_role=staff.role, action=action, entity="infra_cost", entity_id=str(c.id) if c else "-",
                       entity_name=(f"{c.provider} {c.month}" if c else None), detail=detail[:500] or None))


def _err(e: ic.InfraError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


def _range(first: Optional[str], last: Optional[str]) -> tuple:
    """Por defecto los últimos 12 meses terminando en el actual."""
    try:
        last = ic.valid_month(last) if last else ic.current_month()
        first = ic.valid_month(first) if first else ic.month_add(last, -11)
        ic.months_between(first, last)
    except ic.InfraError as e:
        raise _err(e) from None
    return first, last


def _get(db: Session, cost_id: int) -> InfraCost:
    c = db.get(InfraCost, cost_id)
    if not c:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    return c


def _need_table(db: Session) -> None:
    """Si la migración 0121 no está aplicada, un mensaje claro (503) en vez de un error técnico."""
    if not ic.table_ready(db):
        raise HTTPException(status_code=503, detail=ic.TABLE_MISSING)


@router.get("/gastos/infra/status")
def status(db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Qué está conectado y qué falta (sin valores, solo nombres de variables). Responde SIEMPRE, aunque la tabla de gastos aún no exista: la pantalla nunca queda en blanco."""
    return {"table_ready": ic.table_ready(db), "table_message": None if ic.table_ready(db) else ic.TABLE_MISSING, "connections": ic.connections(db),
            "csv_columns": "mes, concepto, monto (y opcionales: proveedor, tipo, moneda, trm, nota)"}


@router.get("/gastos/infra/summary")
def summary(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    _need_table(db)
    first, last = _range(from_, to)
    s = ic.summary(db, first, last)
    s["from"], s["to"] = first, last
    s["providers"] = {k: v[0] for k, v in ic.PROVIDERS.items()}
    return s


@router.get("/gastos/infra/costs")
def list_costs(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    _need_table(db)
    first, last = _range(from_, to)
    return {"costs": ic.export_rows(db, first, last), "from": first, "to": last}


@router.post("/gastos/infra/costs")
def create_cost(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    _need_table(db)
    try:
        f = ic.clean_entry(data)
    except ic.InfraError as e:
        raise _err(e) from None
    c = InfraCost(source="manual", created_by_id=staff.id, **f)
    db.add(c)
    db.flush()
    _audit(db, staff, "create", c, f"{c.kind} {c.currency}")
    db.commit()
    return ic.row_dict(c)


@router.put("/gastos/infra/costs/{cost_id}")
def update_cost(cost_id: int, data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    c = _get(db, cost_id)
    try:
        f = ic.clean_entry(data)
    except ic.InfraError as e:
        raise _err(e) from None
    for k, v in f.items():
        setattr(c, k, v)
    if c.source in ("gcp_export", "archivo"):              # lo corregido a mano ya no lo pisa la importación automática ni un archivo nuevo
        c.source, c.source_key = "manual", None
    c.updated_at = utcnow()
    _audit(db, staff, "edit", c, f"{c.kind} {c.currency}")
    db.commit()
    return ic.row_dict(c)


@router.delete("/gastos/infra/costs/{cost_id}")
def delete_cost(cost_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    c = _get(db, cost_id)
    key = c.attachment_key
    _audit(db, staff, "delete", c, f"{c.kind} {c.currency}")
    db.delete(c)
    db.commit()
    if key:
        try:
            get_storage().delete(key)
        except Exception:  # noqa: BLE001 — el gasto ya se borró; un adjunto huérfano no debe fallar la petición
            log.warning("no se pudo borrar un adjunto de gasto", exc_info=True)
    return {"ok": True}


@router.post("/gastos/infra/costs/{cost_id}/attachment")
def put_attachment(cost_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    c = _get(db, cost_id)
    ext = ic.ATTACH_TYPES.get((file.content_type or "").lower())
    data = file.file.read(ic.MAX_ATTACH + 1)
    if not ext:
        raise HTTPException(status_code=400, detail="Adjunta un PDF, PNG o JPG")
    if not data:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(data) > ic.MAX_ATTACH:
        raise HTTPException(status_code=400, detail="El archivo pesa más de 5 MB")
    magic = {"pdf": b"%PDF", "png": b"\x89PNG", "jpg": b"\xff\xd8"}[ext]
    if not data.startswith(magic):
        raise HTTPException(status_code=400, detail="El archivo no corresponde al tipo indicado")
    st = get_storage()
    old = c.attachment_key
    key = f"infra-costs/{c.id}/{int(utcnow().timestamp())}.{ext}"
    st.put(key, data)
    name = re.sub(r"[^\w.\- ]", "_", (file.filename or f"adjunto.{ext}"))[:120]
    c.attachment_key, c.attachment_name, c.updated_at = key, name, utcnow()
    _audit(db, staff, "attach", c)
    db.commit()
    if old and old != key:
        try:
            st.delete(old)
        except Exception:  # noqa: BLE001
            log.warning("no se pudo borrar el adjunto anterior", exc_info=True)
    return ic.row_dict(c)


@router.get("/gastos/infra/costs/{cost_id}/attachment")
def get_attachment(cost_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    c = _get(db, cost_id)
    if not c.attachment_key:
        raise HTTPException(status_code=404, detail="Este gasto no tiene adjunto")
    st = get_storage()
    if not st.exists(c.attachment_key):
        raise HTTPException(status_code=404, detail="El adjunto ya no está disponible")
    return st.response(c.attachment_key, filename=c.attachment_name, headers={"Cache-Control": "no-store"})


@router.delete("/gastos/infra/costs/{cost_id}/attachment")
def delete_attachment(cost_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    c = _get(db, cost_id)
    key = c.attachment_key
    c.attachment_key = c.attachment_name = None
    c.updated_at = utcnow()
    _audit(db, staff, "detach", c)
    db.commit()
    if key:
        try:
            get_storage().delete(key)
        except Exception:  # noqa: BLE001
            log.warning("no se pudo borrar el adjunto", exc_info=True)
    return ic.row_dict(c)


@router.put("/gastos/infra/settings")
def put_settings(data: dict, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    try:
        out = ic.save_settings(db, data)
    except ic.InfraError as e:
        raise _err(e) from None
    _audit(db, staff, "settings", None, f"criterio {out['basis']}")
    db.commit()
    return out


@router.post("/gastos/infra/import/google")
def import_google(data: Optional[dict] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    _need_table(db)
    try:
        r = ic.import_google(db, (data or {}).get("month"))
    except ic.InfraError as e:
        raise _err(e) from None
    except Exception as e:  # noqa: BLE001
        log.warning("importación de Google falló: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="No se pudo leer la exportación de facturación de Google (revisa la tabla y los permisos de la cuenta de servicio)") from None
    if not r["configured"]:
        raise HTTPException(status_code=409, detail="Google no está conectado: falta la variable GCP_BILLING_EXPORT_TABLE en este entorno. Mientras tanto registra el gasto a mano o sube un archivo.")
    if r["configured"]:
        _audit(db, staff, "import", None, f"google: {r['imported']} nuevos, {r['updated']} actualizados")
        db.commit()
    return r


@router.post("/gastos/infra/import/csv")
def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Carga gastos desde un CSV (alternativa manual a la conexión con Google). Vuelve a subirse sin duplicar. Máximo 1 MB y 1.000 filas."""
    _need_table(db)
    raw = file.file.read(ic.MAX_CSV_BYTES + 1)
    if len(raw) > ic.MAX_CSV_BYTES:
        raise HTTPException(status_code=400, detail="El archivo es demasiado grande (máximo 1 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")          # Excel en Windows guarda «CSV» en ANSI
    try:
        r = ic.import_csv(db, text)
    except ic.InfraError as e:
        raise _err(e) from None
    _audit(db, staff, "import", None, f"archivo: {r['imported']} nuevos, {r['updated']} actualizados, {r['skipped']} omitidos")
    db.commit()
    return r


@router.get("/gastos/infra/neon-usage")
def neon_usage(month: Optional[str] = None, staff: StaffUser = Depends(ADMIN)):
    try:
        return ic.neon_usage(month or ic.current_month())
    except ic.InfraError as e:
        raise _err(e) from None


@router.get("/gastos/infra/export.xlsx")
def export_xlsx(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    first, last = _range(from_, to)
    return Response(ic.build_workbook(db, first, last), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="gastos-infraestructura-{first}-a-{last}.xlsx"', "Cache-Control": "no-store"})
