"""API del importador de SuiteCRM (C1c). Solo administradores. Con CRM_ENABLED apagado responde 404; la carga real exige CRM_IMPORT_APPLY=1."""
import json
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit_actions, jobs
from app.crm.importer import runner
from app.crm.importer.gz import maybe_gunzip
from app.database import get_db
from app.models import CrmImportPair, CrmImportRun, StaffUser
from app.routers import crm as crm_router
from app.routers.crm import _run, admin_staff
from app.timeutil import utcnow

router = APIRouter(prefix="/crm/import", tags=["crm-import"], dependencies=[Depends(crm_router._require_crm_enabled)])
CONFIRM_WORD = "CARGAR"
MODES = ("sample", "dry_run", "apply")


def apply_enabled() -> bool:
    return os.environ.get("CRM_IMPORT_APPLY", "0") == "1"


def _run_dict(r: CrmImportRun) -> dict:
    return {"id": r.id, "mode": r.mode, "status": r.status, "files": json.loads(r.files_json or "{}"), "counts": json.loads(r.counts_json or "{}"), "error": r.error,
            "created_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None, "apply_enabled": apply_enabled()}


def _unpack(raw: bytes) -> bytes:
    try:
        return maybe_gunzip(raw)
    except ValueError as exc:
        raise runner.CrmError(str(exc)) from exc


@router.post("/runs")
def start_run(mode: str = Form(...), accounts: Optional[UploadFile] = File(None), contacts: Optional[UploadFile] = File(None), products: Optional[UploadFile] = File(None),
              opportunities: Optional[UploadFile] = File(None), activities: Optional[UploadFile] = File(None), quotes: Optional[UploadFile] = File(None),
              quote_lines: Optional[UploadFile] = File(None), proformas: Optional[UploadFile] = File(None), confirm: str = Form(""),
              dry_run_id: Optional[int] = Form(None), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Modo no válido.")

    def work():
        files = {k: _unpack(f.file.read()) for k, f in (("accounts", accounts), ("contacts", contacts), ("products", products), ("opportunities", opportunities),
                                                    ("activities", activities), ("quotes", quotes), ("quote_lines", quote_lines), ("proformas", proformas)) if f is not None}
        if not files:
            raise runner.CrmError("Sube al menos un archivo.")
        if mode == "apply":
            if not apply_enabled():
                raise runner.CrmError("La carga real está desactivada en este entorno.", 403)
            if confirm.strip() != CONFIRM_WORD:
                raise runner.CrmError(f"Para cargar escribe «{CONFIRM_WORD}».")
            prev = db.get(CrmImportRun, dry_run_id) if dry_run_id else None
            if prev is None or prev.mode != "dry_run" or prev.status != "done":
                raise runner.CrmError("Antes de cargar hay que terminar una corrida de prueba (dry_run) con los mismos archivos.")
            same = {k: runner.sha256(v) for k, v in files.items()} == {k: v["sha256"] for k, v in json.loads(prev.files_json or "{}").items()}
            if not same:
                raise runner.CrmError("Los archivos no son los mismos de la corrida de prueba.")
        row = CrmImportRun(kind="suitecrm", mode=mode, status="queued", started_by_id=staff.id, options_json="{}")
        db.add(row)
        db.flush()
        row.files_json = json.dumps(runner.store_files(row.id, files))
        jobs.enqueue(db, "crm_import", {"run_id": row.id}, dedupe_key=f"crm_import:{row.id}", max_attempts=1)
        audit_actions.record(db, staff, "import", "crm_import_run", row.id, None, f"modo {mode}")
        return _run_dict(row)

    out = _run(db, work)
    jobs.kick()
    return out


@router.get("/runs")
def list_runs(db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    return {"items": [_run_dict(r) for r in db.query(CrmImportRun).order_by(CrmImportRun.id.desc()).limit(20).all()], "apply_enabled": apply_enabled()}


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    r = db.get(CrmImportRun, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return _run_dict(r)


@router.get("/runs/{run_id}/pairs")
def list_pairs(run_id: int, bucket: str = "", db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    q = db.query(CrmImportPair).filter(CrmImportPair.run_id == run_id)
    if bucket:
        q = q.filter(CrmImportPair.bucket == bucket)
    return {"items": [{"id": p.id, "tenant_name": p.tenant_name, "suitecrm_name": p.suitecrm_name, "suitecrm_code": p.suitecrm_code, "score": p.score, "bucket": p.bucket,
                       "decision": p.decision} for p in q.order_by(CrmImportPair.bucket, CrmImportPair.score.desc()).limit(500).all()]}


class DecideIn(BaseModel):
    pair_ids: List[int]
    decision: str


@router.post("/runs/{run_id}/pairs/decide")
def decide(run_id: int, data: DecideIn, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    if data.decision not in ("approved", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="Decisión no válida.")

    def work():
        n = 0
        for p in db.query(CrmImportPair).filter(CrmImportPair.run_id == run_id, CrmImportPair.id.in_(data.pair_ids[:500]), CrmImportPair.decision != "applied").all():
            if data.decision == "approved" and (p.tenant_id is None or p.suitecrm_code is None):
                continue
            p.decision, p.decided_by_id, p.decided_at = data.decision, staff.id, utcnow()
            n += 1
        return {"updated": n}
    return _run(db, work)


@router.post("/runs/{run_id}/pairs/apply")
def apply_pairs(run_id: int, confirm: str = Form(""), db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        if not apply_enabled():
            raise runner.CrmError("La carga real está desactivada en este entorno.", 403)
        if confirm.strip() != CONFIRM_WORD:
            raise runner.CrmError(f"Para aplicar escribe «{CONFIRM_WORD}».")
        out = runner.apply_pairs(db, run_id)
        audit_actions.record(db, staff, "import", "crm_import_pairs", run_id, None, f"aplicadas {out['applied']}")
        return out
    return _run(db, work)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(admin_staff)):
    def work():
        r = db.get(CrmImportRun, run_id)
        if r is None:
            raise runner.CrmError("Corrida no encontrada.", 404)
        if r.status in ("queued", "running"):
            r.status, r.finished_at = "cancelled", utcnow()
        return _run_dict(r)
    return _run(db, work)
