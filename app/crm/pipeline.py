"""Embudos y etapas del CRM (C2). Sin commit propio: quien llama (el router) confirma o revierte.

* Un embudo (p. ej. «Eventos») tiene etapas ordenadas; las de tipo «ganada» y «perdida» cierran la oportunidad y SIEMPRE van al final.
* Cada embudo conserva al menos una etapa abierta, una ganada y una perdida sin archivar.
* El catálogo (embudos + etapas) cambia casi nunca y lo piden todas las pantallas: se guarda en memoria del proceso, como datos simples, `CATALOG_TTL` segundos; al editar se descarta en este
  proceso (los demás lo renuevan al vencer). Así el tablero no hace una consulta extra por cada carga.
"""
import time
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crm.errors import CrmError
from app.crm.pipeline_rules import check_stage_set, clean_pipeline, clean_stage
from app.models import CrmOpportunity, CrmPipeline, CrmStage, StaffUser
from app.timeutil import utcnow

CATALOG_TTL = 30.0
_cache: dict = {"at": 0.0, "data": None}


def invalidate() -> None:
    _cache["at"], _cache["data"] = 0.0, None


def _serialize(pipelines, stages) -> list:
    by_pipe: dict = {}
    for s in stages:
        by_pipe.setdefault(s.pipeline_id, []).append({"id": s.id, "name": s.name, "position": s.position, "probability": s.probability, "kind": s.kind, "archived": s.archived_at is not None})
    return [{"id": p.id, "name": p.name, "position": p.position, "is_default": bool(p.is_default), "archived": p.archived_at is not None, "stages": by_pipe.get(p.id, [])} for p in pipelines]


def catalog(db: Session, *, fresh: bool = False) -> list:
    """Embudos con sus etapas (incluye archivados; quien muestra filtra). Dos consultas como mucho, y ninguna si el catálogo en memoria está vigente."""
    now = time.monotonic()
    if not fresh and _cache["data"] is not None and now - _cache["at"] < CATALOG_TTL:
        return _cache["data"]
    pipelines = db.query(CrmPipeline).order_by(CrmPipeline.position, CrmPipeline.id).all()
    stages = db.query(CrmStage).order_by(CrmStage.pipeline_id, CrmStage.position, CrmStage.id).all()
    data = _serialize(pipelines, stages)
    _cache["at"], _cache["data"] = now, data
    return data


def live_catalog(db: Session) -> list:
    """Solo lo vigente: embudos y etapas sin archivar (lo que ven los formularios y el tablero)."""
    out = []
    for p in catalog(db):
        if p["archived"]:
            continue
        out.append({**p, "stages": [s for s in p["stages"] if not s["archived"]]})
    return out


def default_pipeline_id(db: Session) -> int:
    live = live_catalog(db)
    for p in live:
        if p["is_default"]:
            return p["id"]
    if live:
        return live[0]["id"]
    raise CrmError("No hay ningún embudo. Un administrador debe crear uno en «Embudos».", 409)


def first_open_stage(db: Session, pipeline_id: int) -> int:
    for p in live_catalog(db):
        if p["id"] == pipeline_id:
            for s in p["stages"]:
                if s["kind"] == "open":
                    return s["id"]
    raise CrmError("El embudo no tiene una etapa abierta.", 409)


def stage_info(db: Session, stage_id: int) -> Optional[dict]:
    """La etapa (con su embudo) desde el catálogo en memoria, o None si no existe. Sin consulta propia."""
    for p in catalog(db):
        for s in p["stages"]:
            if s["id"] == stage_id:
                return {**s, "pipeline_id": p["id"], "pipeline_archived": p["archived"]}
    return None


# ------------------------------------------------------------------ embudos
def _get_pipeline(db: Session, pipeline_id: int) -> CrmPipeline:
    p = db.get(CrmPipeline, pipeline_id)
    if p is None:
        raise CrmError("Embudo no encontrado.", 404)
    return p


def _get_stage(db: Session, stage_id: int) -> CrmStage:
    s = db.get(CrmStage, stage_id)
    if s is None:
        raise CrmError("Etapa no encontrada.", 404)
    return s


def _name_taken(db: Session, model, name: str, *, pipeline_id: Optional[int] = None, except_id: Optional[int] = None) -> bool:
    q = db.query(model.id).filter(func.lower(model.name) == name.lower())
    if pipeline_id is not None:
        q = q.filter(CrmStage.pipeline_id == pipeline_id)
    if except_id is not None:
        q = q.filter(model.id != except_id)
    return q.first() is not None


def create_pipeline(db: Session, staff: StaffUser, data: dict) -> CrmPipeline:
    fields = clean_pipeline(data)
    if not fields.get("name"):
        raise CrmError("El embudo necesita un nombre.")
    if _name_taken(db, CrmPipeline, fields["name"]):
        raise CrmError("Ya existe un embudo con ese nombre.", 409)
    position = (db.query(func.max(CrmPipeline.position)).scalar() or 0) + 1
    p = CrmPipeline(name=fields["name"], position=position, is_default=False)
    db.add(p)
    db.flush()
    for i, (name, prob, kind) in enumerate((("Nuevo", 10, "open"), ("Ganada", 100, "won"), ("Perdida", 0, "lost"))):
        db.add(CrmStage(pipeline_id=p.id, name=name, probability=prob, kind=kind, position=i))
    db.flush()
    invalidate()
    return p


def rename_pipeline(db: Session, pipeline_id: int, data: dict) -> CrmPipeline:
    p = _get_pipeline(db, pipeline_id)
    fields = clean_pipeline(data)
    if not fields.get("name"):
        raise CrmError("El embudo necesita un nombre.")
    if _name_taken(db, CrmPipeline, fields["name"], except_id=p.id):
        raise CrmError("Ya existe un embudo con ese nombre.", 409)
    p.name = fields["name"]
    db.flush()
    invalidate()
    return p


def set_default(db: Session, pipeline_id: int) -> CrmPipeline:
    p = _get_pipeline(db, pipeline_id)
    if p.archived_at is not None:
        raise CrmError("Un embudo archivado no puede ser el predeterminado.")
    db.query(CrmPipeline).filter(CrmPipeline.is_default.is_(True), CrmPipeline.id != p.id).update({"is_default": False}, synchronize_session=False)
    p.is_default = True
    db.flush()
    invalidate()
    return p


def set_pipeline_archived(db: Session, pipeline_id: int, archived: bool) -> CrmPipeline:
    p = _get_pipeline(db, pipeline_id)
    if archived == (p.archived_at is not None):
        raise CrmError("El embudo ya está archivado." if archived else "El embudo no está archivado.")
    if archived:
        if p.is_default:
            raise CrmError("El embudo predeterminado no se archiva. Elige otro como predeterminado primero.")
        if db.query(CrmOpportunity.id).filter(CrmOpportunity.pipeline_id == p.id, CrmOpportunity.outcome == "open").first() is not None:
            raise CrmError("El embudo tiene oportunidades abiertas. Muévelas o ciérralas antes de archivarlo.", 409)
    p.archived_at = utcnow() if archived else None
    db.flush()
    invalidate()
    return p


# ------------------------------------------------------------------ etapas
def _renumber(db: Session, pipeline_id: int) -> None:
    """Las abiertas primero (en su orden), después las ganadas y perdidas; posiciones 0, 1, 2…"""
    stages = db.query(CrmStage).filter(CrmStage.pipeline_id == pipeline_id).order_by(CrmStage.position, CrmStage.id).all()
    order = {"open": 0, "won": 1, "lost": 2}
    for i, s in enumerate(sorted(stages, key=lambda s: (order.get(s.kind, 0), s.position, s.id))):
        s.position = i
    db.flush()


def create_stage(db: Session, pipeline_id: int, data: dict) -> CrmStage:
    p = _get_pipeline(db, pipeline_id)
    fields = clean_stage(data)
    if not fields.get("name"):
        raise CrmError("La etapa necesita un nombre.")
    if _name_taken(db, CrmStage, fields["name"], pipeline_id=p.id):
        raise CrmError("Ya existe una etapa con ese nombre en este embudo.", 409)
    kind = fields.get("kind", "open")
    s = CrmStage(pipeline_id=p.id, name=fields["name"], kind=kind, probability=fields.get("probability", 10 if kind == "open" else 100 if kind == "won" else 0),
                 position=(db.query(func.max(CrmStage.position)).filter(CrmStage.pipeline_id == p.id).scalar() or 0) + 1)
    db.add(s)
    db.flush()
    _renumber(db, p.id)
    invalidate()
    return s


def _live_kinds(db: Session, pipeline_id: int, *, replace: Optional[tuple] = None) -> list:
    out = []
    for s in db.query(CrmStage).filter(CrmStage.pipeline_id == pipeline_id).all():
        if replace is not None and s.id == replace[0]:
            out.append((replace[1], replace[2]))
        else:
            out.append((s.kind, s.archived_at is not None))
    return out


def update_stage(db: Session, stage_id: int, data: dict) -> CrmStage:
    s = _get_stage(db, stage_id)
    fields = clean_stage(data)
    if "name" in fields:
        if not fields["name"]:
            raise CrmError("La etapa necesita un nombre.")
        if _name_taken(db, CrmStage, fields["name"], pipeline_id=s.pipeline_id, except_id=s.id):
            raise CrmError("Ya existe una etapa con ese nombre en este embudo.", 409)
    if "kind" in fields and fields["kind"] != s.kind:
        if db.query(CrmOpportunity.id).filter(CrmOpportunity.stage_id == s.id).first() is not None:
            raise CrmError("Esta etapa ya tiene oportunidades: no se puede cambiar su tipo.", 409)
        check_stage_set(_live_kinds(db, s.pipeline_id, replace=(s.id, fields["kind"], s.archived_at is not None)))
    for key, value in fields.items():
        setattr(s, key, value)
    db.flush()
    if "kind" in fields:
        _renumber(db, s.pipeline_id)
    invalidate()
    return s


def reorder_stages(db: Session, pipeline_id: int, ordered_ids: list) -> list:
    """Reordena las etapas ABIERTAS del embudo. Debe venir exactamente el conjunto de las abiertas sin archivar; las ganadas y perdidas siguen al final."""
    p = _get_pipeline(db, pipeline_id)
    stages = db.query(CrmStage).filter(CrmStage.pipeline_id == p.id).all()
    wanted = [s for s in stages if s.kind == "open" and s.archived_at is None]
    try:
        ids = [int(i) for i in ordered_ids]
    except (TypeError, ValueError) as exc:
        raise CrmError("El orden de las etapas no es válido.") from exc
    if len(ids) != len(set(ids)) or set(ids) != {s.id for s in wanted}:
        raise CrmError("El orden debe incluir exactamente las etapas abiertas del embudo.")
    pos = {sid: i for i, sid in enumerate(ids)}
    base = len(ids)
    for s in stages:
        s.position = pos[s.id] if s.id in pos else base + s.position + 1          # archivadas y cerradas detrás de las abiertas vigentes, en su orden
    db.flush()
    _renumber(db, p.id)
    invalidate()
    return stages


def set_stage_archived(db: Session, stage_id: int, archived: bool) -> CrmStage:
    s = _get_stage(db, stage_id)
    if archived == (s.archived_at is not None):
        raise CrmError("La etapa ya está archivada." if archived else "La etapa no está archivada.")
    if archived:
        if db.query(CrmOpportunity.id).filter(CrmOpportunity.stage_id == s.id, CrmOpportunity.outcome == "open").first() is not None:
            raise CrmError("La etapa tiene oportunidades abiertas. Muévelas a otra etapa antes de archivarla.", 409)
        check_stage_set(_live_kinds(db, s.pipeline_id, replace=(s.id, s.kind, True)))
    s.archived_at = utcnow() if archived else None
    db.flush()
    invalidate()
    return s
