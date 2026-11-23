"""Base de DEPENDIENTES de un evento (21-nov-2026, docs/25_INVENTARIO_POR_BASE.md): un segundo archivo con las personas que vienen asociadas a un titular (hijos, acompañantes),
enlazadas por la cédula del titular. El titular es la persona de la base de registro del evento; el dependiente NO es una persona del evento (no tiene rostro, no cuenta como
registrado, no entra a la ruleta): aparece en el campo «Dependientes» de su titular, en los reportes y, si el inventario lo define la base, con lo que le toca.

Carga en dos tiempos: `analyze` (vista previa, NO escribe nada) y `apply` (reemplazar o agregar). Reemplazar borra lo pendiente y vuelve a crearlo con el archivo; lo ya ENTREGADO
nunca se borra ni se repite. Nada de datos personales en los logs: solo conteos."""
import json
import logging
import uuid
from collections import Counter, defaultdict

from fastapi import HTTPException
from sqlalchemy import func

from app import inv_assign_core as core
from app import testperson
from app.models import AccessLog, EventAttendee, EventDependent, InventoryDelivery, User
from app.timeutil import utcnow

log = logging.getLogger("golden.dependents")
MAX_ROWS = 20000
CHUNK = 2000
MODES = ("replace", "append")
NEEDS_HOLDER = ("El archivo de dependientes debe traer la columna con la cédula del TITULAR (por ejemplo «cedula_titular»): es la que une a cada dependiente con la persona "
                "de la base de registro. Descarga el archivo de ejemplo si no tienes el formato.")


def _chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def has_dependents(db, event_id: int) -> bool:
    return db.query(EventDependent.id).filter(EventDependent.event_id == event_id).first() is not None


def event_people_ids(db, event, ids) -> set:
    out = set()
    for part in _chunks(ids):
        out.update(r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id, EventAttendee.user_id.in_(part)))
    return out


def registered_ids(db, event, ids) -> set:
    """Quiénes de `ids` están REGISTRADOS en el evento (tienen un ingreso que no es solo «Actualizado»: la misma regla de Estadísticas)."""
    out = set()
    for part in _chunks(ids):
        out.update(r[0] for r in db.query(AccessLog.user_id).filter(AccessLog.event_id == event.id, AccessLog.user_id.in_(part), AccessLog.record_type != "Actualizado").distinct())
    return out


def is_registered(db, event, user_id: str) -> bool:
    return bool(registered_ids(db, event, [user_id]))


def _row_json(r: EventDependent) -> dict:
    return {"id": r.id, "uid": r.uid, "holder": r.holder_id, "name": r.name or "", "doc": r.doc_id or "", "person_key": r.person_key, "data": r.get_data(), "row_num": r.row_num}


def rows_of_holders(db, event, holder_ids) -> dict:
    """{titular: [filas]} en el orden del archivo."""
    out = defaultdict(list)
    for part in _chunks(holder_ids):
        for r in db.query(EventDependent).filter(EventDependent.event_id == event.id, EventDependent.holder_id.in_(part)).order_by(EventDependent.id):
            out[r.holder_id].append(_row_json(r))
    return out


def people_of(db, event, holder_id: str) -> list:
    """Los dependientes de un titular, agrupados (una persona con varios productos = varias filas), con su etiqueta «Dependiente N» si no traen nombre."""
    return core.group_people(rows_of_holders(db, event, [holder_id]).get(holder_id, []))


def own_rows(db, event, user_id: str) -> list:
    """Filas donde esta persona ES el dependiente (su propio documento viene en la columna del dependiente de OTRO titular): se le entrega a ella directamente."""
    return [_row_json(r) for r in db.query(EventDependent).filter(EventDependent.event_id == event.id, EventDependent.doc_id == user_id, EventDependent.holder_id != user_id).order_by(EventDependent.id)]


def counts_by_holder(db, event) -> dict:
    """{titular: cuántos dependientes (personas, no filas)}. Un dependiente que además está en la base del evento con su propio documento no se cuenta (ya cuenta como persona)."""
    people = defaultdict(set)
    docs = set()
    for holder, key, doc in db.query(EventDependent.holder_id, EventDependent.person_key, EventDependent.doc_id).filter(EventDependent.event_id == event.id):
        people[holder].add((key, doc or ""))
        if doc:
            docs.add(doc)
    in_event = event_people_ids(db, event, docs) if docs else set()
    return {h: sum(1 for (_k, d) in ks if not (d and d in in_event)) for h, ks in people.items()}


def search(db, event, q: str, limit: int = 15) -> list:
    """Busca dependientes por nombre o documento (mínimo 3 caracteres). Devuelve a quién se le entrega: su titular (o ella misma si está en la base con su documento)."""
    text = core.norm(q)
    raw = core.clean_id(q)
    if len(text) < 3 and len(raw) < 3:
        return []
    hits = []
    query = db.query(EventDependent).filter(EventDependent.event_id == event.id)
    like = str(q).strip().lower()[:60].replace("\\", "").replace("%", "").replace("_", "")
    for r in query.filter((EventDependent.doc_id == raw) | (func.lower(EventDependent.name).like(f"%{like}%"))).order_by(EventDependent.id).limit(200):
        hits.append(r)
    if len(hits) < limit:          # nombres con tildes o espacios distintos: comparación normalizada sobre un tope de filas
        seen = {h.id for h in hits}
        for r in query.filter(EventDependent.name.isnot(None)).order_by(EventDependent.id).limit(5000):
            if r.id not in seen and text and text in core.norm(r.name):
                hits.append(r)
                if len(hits) >= 200:
                    break
    holders = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(list({h.holder_id for h in hits}) or [""]))}
    out, keys = [], set()
    for r in hits:
        k = (r.holder_id, r.person_key)
        if k in keys:
            continue
        keys.add(k)
        u = holders.get(r.holder_id)
        out.append({"dependent": r.name or "", "doc": r.doc_id or "", "holder_id": r.holder_id,
                    "holder_name": f"{(u.first_name or '') if u else ''} {(u.last_name or '') if u else ''}".strip()})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------ carga (vista previa y escritura)
def read_file(filename: str, content: bytes):
    """(títulos, filas) con la MISMA lectura de la base de personas (xlsx o csv, topes de tamaño). Los títulos quedan en minúsculas, como en la carga de personas."""
    from app.routers.api import _read_roster_rows
    header_columns, rows = _read_roster_rows(filename, content)
    if len(rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"El archivo tiene {len(rows):,} filas y el máximo de la base de dependientes es {MAX_ROWS:,}. Divídelo en varios archivos y cárgalos con «Agregar».".replace(",", "."))
    if not rows:
        raise HTTPException(status_code=400, detail="El archivo no tiene filas de datos.")
    return list(header_columns.keys()), rows


def _signature(r: dict, sig_cols=None) -> tuple:
    """Lo que hace que dos filas sean «la misma» entre una carga y la siguiente: titular, dependiente y lo que define LA ASIGNACIÓN (columnas de producto y cantidad; sin ellas, todas).
    Las demás columnas (edad, notas…) se pueden corregir sin que la fila pase a ser otra: si no, una fila ya entregada se duplicaba y volvía a quedar pendiente (staging, 21-nov-2026).
    El dependiente sin nombre ni documento (`row:N`) se identifica por su producto, no por el número de fila: reordenar el archivo no lo cambia."""
    items = (r.get("data") or {}).items()
    if sig_cols:
        items = [(k, v) for k, v in items if core.norm(k) in sig_cols]
    data = tuple(sorted((core.norm(k), core.norm(v)) for k, v in items))
    pk = r["person_key"]
    return (r["holder"], "row" if pk.startswith("row:") else pk, data)


def analyze(db, event, titles: list, rows: list, mode: str = "replace", dep_product: str = None, dep_qty: str = None) -> dict:
    """Vista previa SIN escribir nada: qué columnas se reconocieron, qué filas se cargan y cuáles no (y por qué), cómo cambia el campo «Dependientes» de los titulares y
    una muestra repartida de hasta 10 titulares tal como se verían en «Editar persona»."""
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Elige «Reemplazar» o «Agregar solo lo nuevo»")
    cols = core.detect_columns(titles)
    if not cols["holder"]:
        raise HTTPException(status_code=400, detail=NEEDS_HOLDER)
    parsed = core.parse_dependent_rows(rows, cols)
    holders = list(dict.fromkeys(p["holder"] for p in parsed if p["holder"]))
    in_event = event_people_ids(db, event, holders)
    registered = registered_ids(db, event, list(in_event))
    docs = list({p["doc"] for p in parsed if p["doc"]})
    docs_in_event = event_people_ids(db, event, docs) if docs else set()

    ok, skipped = [], []
    for p in parsed:
        if not p["holder"]:
            skipped.append({"row": p["row_num"], "reason": "no trae la cédula del titular"})
        elif testperson.is_test(p["holder"]):
            skipped.append({"row": p["row_num"], "reason": "la persona de prueba no lleva dependientes"})
        elif p["holder"] not in in_event:
            skipped.append({"row": p["row_num"], "reason": "el titular no está en la base de este evento (cárgalo primero en la base de registro)"})
        else:
            ok.append(p)

    existing = [_row_json(r) for r in db.query(EventDependent).filter(EventDependent.event_id == event.id).order_by(EventDependent.id)]
    delivered_ids = _delivered_row_ids(db, event)
    sig_cols = {core.norm(c) for c in (dep_product, dep_qty) if c}
    if not sig_cols:
        sig_cols = {c for c in ("producto", "cantidad") if any(core.norm(t) == c for t in titles)}
    plan = _plan(existing, ok, mode, delivered_ids, sig_cols)

    before = _people_count(existing)
    after_rows = plan["keep"] + plan["insert"]          # (las filas «actualizadas» ya traen sus datos nuevos)
    after = _people_count(after_rows)
    holders_before, holders_after = Counter(), Counter()
    for h, n in before.items():
        holders_before[h] = n
    for h, n in after.items():
        holders_after[h] = n
    changed = [h for h in set(holders_before) | set(holders_after) if holders_before[h] != holders_after[h]]

    product_col = core.norm(dep_product) if dep_product else ("producto" if any("producto" in {core.norm(k) for k in p["data"]} for p in ok) else "")
    products = Counter()
    if product_col:
        for p in ok:
            v = next((val for k, val in p["data"].items() if core.norm(k) == product_col), "")
            if v:
                products[core.norm(v)] += 1

    # muestra repartida: hasta 10 titulares del archivo (de punta a punta), con sus dependientes tal como quedarían
    ok_holders = list(dict.fromkeys(p["holder"] for p in ok))
    sample_h = [ok_holders[i] for i in core.sample_indices(len(ok_holders))]
    users = {u.id: u for u in db.query(User).filter(User.tenant_id == event.tenant_id, User.id.in_(sample_h or [""]))}
    by_holder_after = defaultdict(list)
    for r in after_rows:
        if r["holder"] in sample_h:
            by_holder_after[r["holder"]].append(r)
    samples = []
    for h in sample_h:
        u = users.get(h)
        people = core.group_people(by_holder_after.get(h, []))
        samples.append({
            "holder": h, "holder_name": f"{(u.first_name or '') if u else ''} {(u.last_name or '') if u else ''}".strip(),
            "registered": h in registered, "before": holders_before[h], "after": holders_after[h],
            "people": [{"label": p["label"], "doc": p["doc"], "own_person": bool(p["doc"] and p["doc"] in docs_in_event),
                        "rows": [{"data": r.get("data") or {}} for r in p["rows"]]} for p in people],
        })
    return {
        "mode": mode,
        "columns": {"holder": cols["holder"], "name": cols["name"], "doc": cols["doc"],
                    "others": [t for t in titles if t not in (cols["holder"], cols["name"], cols["doc"])]},
        "rows": len(parsed), "loaded_rows": len(ok), "skipped": skipped[:200], "skipped_count": len(skipped),
        "holders": len(ok_holders), "holders_not_registered": sum(1 for h in ok_holders if h not in registered),
        "own_person_rows": sum(1 for p in ok if p["doc"] and p["doc"] in docs_in_event),
        "dependents_before": sum(before.values()), "dependents_after": sum(after.values()),
        "holders_with_dependents_before": len(before), "holders_with_dependents_after": len(after),
        "holders_changed": len(changed),
        "insert_rows": len(plan["insert"]), "updated_rows": len(plan["update"]), "delete_rows": len(plan["delete"]), "kept_rows": len(plan["keep"]), "kept_delivered": plan["kept_delivered"],
        "products": len(products), "product_column": product_col,
        "samples": samples,
        "_plan": plan,
    }


def _people_count(rows: list) -> dict:
    out = defaultdict(set)
    for r in rows:
        out[r["holder"]].add(r["person_key"])
    return {h: len(v) for h, v in out.items()}


def _delivered_row_ids(db, event) -> set:
    """uid de las filas de dependientes que ya tienen alguna entrega."""
    out = set()
    for (key,) in db.query(InventoryDelivery.assignment_key).filter(InventoryDelivery.event_id == event.id, InventoryDelivery.assignment_key.like(core.DEP_PREFIX + "%")).distinct():
        if key and key != core.HOLDER_KEY:
            out.add(str(key)[len(core.DEP_PREFIX):])
    return out


def _plan(existing: list, incoming: list, mode: str, delivered_ids: set, sig_cols=None) -> dict:
    """Qué filas se conservan, cuáles se borran y cuáles se crean. Una fila del archivo que ya existe (misma firma) se conserva (así su asignación y lo entregado siguen enlazados) y,
    al reemplazar, recibe los datos nuevos de las demás columnas. Reemplazar: lo que ya no viene se borra, salvo lo ya entregado. Agregar: no se borra ni se cambia nada."""
    pool = defaultdict(list)
    for r in existing:
        pool[_signature(r, sig_cols)].append(r)
    keep, insert, update = [], [], []
    for r in incoming:
        sig = _signature(r, sig_cols)
        if pool.get(sig):
            old = pool[sig].pop(0)
            if mode != "append" and (old.get("data") or {}) != (r.get("data") or {}):
                new_row = dict(old, data=r.get("data") or {})
                update.append(new_row)
                keep.append(new_row)
            else:
                keep.append(old)
        else:
            if r["person_key"].startswith("row:"):
                r = dict(r, person_key=f"row:n{r['row_num']}")          # único: no choca con la clave de una fila conservada
            insert.append(r)
    leftover = [r for rows in pool.values() for r in rows]
    if mode == "append":
        keep += leftover
        delete = []
        kept_delivered = 0
    else:
        delete = [r for r in leftover if r["uid"] not in delivered_ids]
        still = [r for r in leftover if r["uid"] in delivered_ids]
        keep += still
        kept_delivered = len(still)
    return {"keep": keep, "insert": insert, "delete": delete, "update": update, "kept_delivered": kept_delivered}


def apply(db, event, staff, analysis: dict) -> dict:
    """Escribe lo que la vista previa planeó (la misma función la arma otra vez con el mismo archivo, así no se confía en nada que mande el navegador)."""
    plan = analysis["_plan"]
    del_ids = [r["id"] for r in plan["delete"]]
    for part in _chunks(del_ids):
        db.query(EventDependent).filter(EventDependent.event_id == event.id, EventDependent.id.in_(part)).delete(synchronize_session=False)
    for r in plan["update"]:
        db.query(EventDependent).filter(EventDependent.event_id == event.id, EventDependent.id == r["id"]).update(
            {"data_json": json.dumps(r["data"], ensure_ascii=False) if r["data"] else None}, synchronize_session=False)
    now = utcnow()
    db.add_all([EventDependent(event_id=event.id, tenant_id=event.tenant_id, uid=uuid.uuid4().hex[:24], holder_id=r["holder"], person_key=r["person_key"][:200], name=(r["name"] or None),
                               doc_id=(r["doc"] or None), data_json=json.dumps(r["data"], ensure_ascii=False) if r["data"] else None, row_num=r["row_num"], created_at=now)
                for r in plan["insert"]])
    db.flush()
    log.info("dependientes: evento=%s modo=%s nuevas=%s borradas=%s conservadas=%s", event.id, analysis["mode"], len(plan["insert"]), len(del_ids), len(plan["keep"]))
    return {"inserted": len(plan["insert"]), "updated": len(plan["update"]), "deleted": len(del_ids), "kept": len(plan["keep"]), "kept_delivered": plan["kept_delivered"],
            "dependents": analysis["dependents_after"], "holders": analysis["holders_with_dependents_after"], "skipped": analysis["skipped_count"]}


def delete_all(db, event) -> dict:
    """Borra la base de dependientes del evento, salvo las filas con entregas (el historial no se borra)."""
    delivered = _delivered_row_ids(db, event)
    q = db.query(EventDependent).filter(EventDependent.event_id == event.id)
    total = q.count()
    if delivered:
        q = q.filter(~EventDependent.uid.in_(list(delivered)))
    n = q.delete(synchronize_session=False)
    return {"deleted": n, "kept_delivered": total - n}


def delete_for_holders(db, event_id: int, holder_ids) -> int:
    """Al sacar personas del evento (o suprimir sus datos) se van también sus dependientes."""
    n = 0
    for part in _chunks([str(i) for i in holder_ids if i]):
        n += db.query(EventDependent).filter(EventDependent.event_id == event_id, EventDependent.holder_id.in_(part)).delete(synchronize_session=False)
    return n


def stats_data(db, event) -> dict:
    """Estadística del campo «Dependientes»: cuántos titulares REGISTRADOS tienen 0, 1, 2… dependientes, y el total de personas que entran contando a sus dependientes.
    La persona de prueba nunca cuenta. Solo conteos."""
    counts = counts_by_holder(db, event)
    att = testperson.drop_test([r[0] for r in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id)])
    reg = registered_ids(db, event, att)
    dist = Counter(counts.get(u, 0) for u in reg)
    buckets = [{"label": f"{n} dependiente{'s' if n != 1 else ''}", "count": dist[n]} for n in sorted(dist)]
    deps_of_registered = sum(counts.get(u, 0) for u in reg)
    total_expected = sum(counts.get(u, 0) for u in att)
    summary = (f"Registrados: {len(reg)} · dependientes asociados a ellos: {deps_of_registered} · personas que entran contando a los dependientes: {len(reg) + deps_of_registered}. "
               f"En toda la base: {len(att)} titulares y {total_expected} dependientes.")
    return {"type": "categorical", "buckets": buckets, "summary": summary,
            "totals": {"registered": len(reg), "dependents_of_registered": deps_of_registered, "with_dependents": len(reg) + deps_of_registered,
                       "base_people": len(att), "base_dependents": total_expected}}
