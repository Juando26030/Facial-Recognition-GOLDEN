"""Importador de SuiteCRM (C1c-1): cuentas y contactos. Tres modos: sample (20 filas por archivo, nada se guarda), dry_run (todo, nada se guarda), apply (guarda).
Un SAVEPOINT por fila: una fila mala se rechaza con un motivo SIN valores de datos y el resto sigue. Idempotente: lo ya importado (legacy_sugar_id) se salta."""
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.crm import accounts as acc_svc, normalize
from app.crm.codes import bump_floor
from app.crm.errors import CrmError
from app.crm.importer import formats, more, scoring
from app.models import CrmAccount, CrmContact, CrmImportPair, CrmImportRun, Tenant
from app.storage import get_storage
from app.timeutil import utcnow

SAMPLE_ROWS = 20
COMMIT_EVERY = 200
FILE_KINDS = ("accounts", "contacts", "products", "opportunities", "activities", "quotes", "quote_lines", "proformas")


def prefix(run_id: int) -> str:
    return f"crm/imports/{run_id}/"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def store_files(run_id: int, files: dict) -> dict:
    """Guarda los archivos subidos (bytes por tipo) y devuelve {tipo: {sha256, bytes}} (sin contenido)."""
    out = {}
    st = get_storage()
    for kind, raw in files.items():
        if kind not in FILE_KINDS:
            raise CrmError("Tipo de archivo no válido.")
        formats.check_headers(kind, raw)                     # valida tamaño, codificación y columnas obligatorias al subir
        st.put(prefix(run_id) + kind + ".csv", raw)
        out[kind] = {"sha256": sha256(raw), "bytes": len(raw)}
    return out


def _reject(rejected: list, lineno: int, reason: str) -> None:
    if len(rejected) < 500:
        rejected.append({"row": lineno, "reason": reason})


def _account_fields(row: dict) -> dict:
    data = {"name": row.get("name"), "nit": row.get("nit"), "phone": row.get("phone"), "email": row.get("email"), "billing_city": row.get("city"),
            "billing_address": row.get("address"), "description": row.get("description")}
    return {k: v for k, v in data.items() if v}


def import_accounts(db: Session, staff_id: int, raw: bytes, mode: str) -> dict:
    limit = SAMPLE_ROWS if mode == "sample" else None
    save = mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0}
    rejected, names, max_code = [], [], 0
    seen_codes = set()
    for lineno, row in formats.read_rows("accounts", raw, limit):
        counts["read"] += 1
        try:
            fields = acc_svc.clean_account(_account_fields(row))          # los mismos topes que la API: demasiado largo → rechazo
            if not fields.get("name"):
                raise CrmError("Fila sin nombre.")
            legacy = (row.get("legacy_id") or "")[:40] or None
            code = int(row["code"]) if (row.get("code") or "").isdigit() else None
            if code is not None and code in seen_codes:
                raise CrmError("Número de cuenta repetido en el archivo.")
            if legacy and db.query(CrmAccount.id).filter(CrmAccount.legacy_sugar_id == legacy).first():
                counts["skipped_existing"] += 1
                continue
            names.append((legacy or f"fila-{lineno}", fields["name"], code))
            if code is not None:
                seen_codes.add(code)
                max_code = max(max_code, code)
            if save:
                with db.begin_nested():
                    from app.crm.codes import next_code
                    db.add(CrmAccount(code=code if code is not None else next_code(db, "account"), name_norm=normalize(fields["name"])[:200], legacy_sugar_id=legacy,
                                      owner_staff_id=staff_id, created_by_id=staff_id, status="activo", **fields))
                    db.flush()
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception:                                              # p. ej. número de cuenta ya existente: sin detalles de la fila
            counts["rejected"] += 1
            _reject(rejected, lineno, "No se pudo guardar la fila (dato repetido o fuera de rango).")
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    if save and max_code:
        bump_floor(db, "account", max_code)
    return {"counts": counts, "rejected": rejected, "names": names, "max_code": max_code}


def import_contacts(db: Session, staff_id: int, raw: bytes, mode: str, virtual: Optional[set] = None) -> dict:
    limit = SAMPLE_ROWS if mode == "sample" else None
    save = mode == "apply"
    counts = {"read": 0, "created": 0, "skipped_existing": 0, "rejected": 0, "without_account": 0}
    rejected = []
    for lineno, row in formats.read_rows("contacts", raw, limit):
        counts["read"] += 1
        try:
            legacy = (row.get("legacy_id") or "")[:40] or None
            if legacy and db.query(CrmContact.id).filter(CrmContact.legacy_sugar_id == legacy).first():
                counts["skipped_existing"] += 1
                continue
            norm = normalize(row.get("account_name"))[:200]
            account = db.query(CrmAccount).filter(CrmAccount.name_norm == norm).first() if norm else None
            if account is None and not save and norm in (virtual or ()):
                account = object()                                       # prueba en seco: la cuenta viene en los archivos de esta corrida
            if account is None:
                counts["without_account"] += 1
                raise CrmError("El contacto no tiene una cuenta conocida.")
            data = {k: row.get(k) for k in ("first_name", "last_name", "job_title", "email", "phone") if row.get(k)}
            acc_svc.clean_contact(data)                                  # valida topes
            if save:
                with db.begin_nested():
                    c = acc_svc.create_contact(db, _Actor(staff_id), account, data)
                    c.legacy_sugar_id = legacy
            counts["created"] += 1
        except CrmError as e:
            counts["rejected"] += 1
            _reject(rejected, lineno, str(e))
        except Exception:
            counts["rejected"] += 1
            _reject(rejected, lineno, "No se pudo guardar la fila.")
        if save and counts["read"] % COMMIT_EVERY == 0:
            db.commit()
    return {"counts": counts, "rejected": rejected}


class _Actor:
    """Lo mínimo de un StaffUser que usan los servicios (el id)."""
    def __init__(self, staff_id: int):
        self.id = staff_id


def build_pairs(db: Session, run_id: int, suite_accounts: list) -> dict:
    """Informe de emparejamiento: clientes de la plataforma ↔ cuentas de SuiteCRM. Solo nombres de EMPRESAS. suite_accounts: [(legacy_id, nombre, número|None)]."""
    tenants = [(t.id, t.name) for t in db.query(Tenant.id, Tenant.name).all()]
    right = [(lid, name) for lid, name, _ in suite_accounts]
    info = {lid: (name, code) for lid, name, code in suite_accounts}
    names = dict(tenants)
    db.query(CrmImportPair).filter(CrmImportPair.run_id == run_id).delete()
    tally = {"seguro": 0, "dudoso": 0, "sin_pareja": 0}
    for tid, rid, sc, bucket in scoring.pair_all(tenants, right):
        tally[bucket] += 1
        sname, scode = info.get(rid, (None, None))
        db.add(CrmImportPair(run_id=run_id, tenant_id=tid, tenant_name=(names[tid] or "")[:200], suitecrm_legacy_id=rid if rid else None, suitecrm_code=scode,
                             suitecrm_name=(sname or "")[:200] or None, score=sc, bucket=bucket))
    db.flush()
    return tally


def apply_pairs(db: Session, run_id: int) -> dict:
    """Aplica SOLO las parejas aprobadas: el cliente pasa al número de SuiteCRM y su hexadecimal queda en `legacy_client_code`."""
    done = skipped = 0
    for p in db.query(CrmImportPair).filter(CrmImportPair.run_id == run_id, CrmImportPair.decision == "approved").all():
        tenant = db.get(Tenant, p.tenant_id) if p.tenant_id else None
        if tenant is None or p.suitecrm_code is None or tenant.client_code == str(p.suitecrm_code):
            skipped += 1
            continue
        clash = db.query(Tenant.id).filter(Tenant.client_code == str(p.suitecrm_code), Tenant.id != tenant.id).first()
        if clash:
            skipped += 1
            continue
        with db.begin_nested():
            if tenant.legacy_client_code is None:
                tenant.legacy_client_code = tenant.client_code
            tenant.client_code = str(p.suitecrm_code)
            p.decision, p.applied_at = "applied", utcnow()
        done += 1
    return {"applied": done, "skipped": skipped}


def run(db: Session, run_id: int) -> None:
    """Ejecuta una corrida completa. Los archivos se borran SIEMPRE al terminar."""
    row = db.get(CrmImportRun, run_id)
    if row is None or row.status in ("done", "cancelled"):
        return
    row.status, row.started_at = "running", row.started_at or utcnow()
    db.commit()
    st = get_storage()
    try:
        summary, suite, grouped = {}, [], None
        files = {k: st.get(prefix(run_id) + k + ".csv") for k in FILE_KINDS if st.exists(prefix(run_id) + k + ".csv")}
        save = row.mode == "apply"
        if "accounts" in files:
            res = import_accounts(db, row.started_by_id, files["accounts"], row.mode)
            suite = res["names"]
            summary["accounts"] = {"counts": res["counts"], "rejected": res["rejected"]}
        if "contacts" in files:
            virtual = {normalize(n)[:200] for _l, n, _c in suite}
            res = import_contacts(db, row.started_by_id, files["contacts"], row.mode, virtual)
            summary["contacts"] = {"counts": res["counts"], "rejected": res["rejected"]}
        later = [k for k in ("products", "opportunities", "activities", "quotes", "proformas") if k in files]
        if later or "quote_lines" in files:
            if save:
                db.commit()
            ctx = more.Ctx(db, save)
            ctx.add_accounts(suite)
            if "quote_lines" in files and "quotes" not in files:
                summary["quote_lines"] = {"counts": {"read": 0}, "rejected": [], "note": "Las líneas se leen junto con las cotizaciones: sube también el archivo de cotizaciones."}
            if "quotes" in files:
                grouped = more.group_lines(files.get("quote_lines"))
            for kind in later:
                if kind == "products":
                    res = more.import_products(ctx, row.started_by_id, files[kind], row.mode)
                elif kind == "opportunities":
                    res = more.import_opportunities(ctx, row.started_by_id, files[kind], row.mode)
                elif kind == "activities":
                    res = more.import_activities(ctx, row.started_by_id, files[kind], row.mode)
                elif kind == "quotes":
                    res = more.import_quotes(ctx, row.started_by_id, files[kind], row.mode, grouped or {})
                else:
                    res = more.import_proformas(ctx, row.started_by_id, files[kind], row.mode)
                summary[kind] = {"counts": res["counts"], "rejected": res["rejected"]}
                if save:
                    db.commit()
        if suite:
            summary["pairs"] = build_pairs(db, run_id, suite)
        row.counts_json = json.dumps(summary)
        row.status, row.finished_at = "done", utcnow()
        db.commit()
    except CrmError as e:
        db.rollback()
        row = db.get(CrmImportRun, run_id)
        row.status, row.error, row.finished_at = "failed", str(e)[:500], utcnow()
        db.commit()
    except Exception:
        db.rollback()
        row = db.get(CrmImportRun, run_id)
        row.status, row.error, row.finished_at = "failed", "Error inesperado durante la importación.", utcnow()
        db.commit()
        raise
    finally:
        try:
            st.delete_prefix(prefix(run_id))
        except Exception:
            pass


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
