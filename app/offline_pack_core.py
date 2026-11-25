"""Paquete para trabajar SIN RED en el quiosco (25-nov-2026, docs/28_CONTINGENCIA_COMPLETA.md): reglas PURAS (sin base de datos ni FastAPI).

Arma, de una sola vez para todo el evento, lo mismo que el servidor responde persona por persona con conexión:
- `dependents`: {titular: [{label, doc, rows}]}  (igual que GET /events/{id}/dependents?holder=…)
- `assigned`:   {cédula: [líneas]}               (igual que `lines` de GET /events/{id}/inventory/assigned?cedula=…), solo en el modo «la base lo define».
La base de datos la pone app/offline_pack.py."""
from collections import defaultdict

from app import inv_assign_core as core


def dependents_view(rows: list) -> tuple:
    """Filas de `event_dependents` (como `dependents._row_json`) -> ({titular: personas agrupadas}, {documento del dependiente: filas donde ÉL es el dependiente de otro titular})."""
    by_holder, own = defaultdict(list), defaultdict(list)
    for r in rows:
        by_holder[r["holder"]].append(r)
        if r.get("doc") and r["doc"] != r["holder"]:
            own[r["doc"]].append(r)
    return {h: core.group_people(rs) for h, rs in by_holder.items()}, own


def public_dependents(people_by_holder: dict) -> dict:
    return {h: [{"label": p["label"], "doc": p["doc"], "rows": [r["data"] for r in p["rows"]]} for p in people] for h, people in people_by_holder.items()}


def assigned_lines(cfg: dict, users: list, people_by_holder: dict, own: dict, items: dict, stock: dict, holder_done: dict, dep_done: dict) -> dict:
    """`users` = [{id, product, qty}] (los valores del titular); `items` = {clave normalizada: {id, name, initial_qty}}; `stock` = {id del producto: entregado};
    `holder_done` = {cédula: unidades de su asignación 'h'}; `dep_done` = {'d<uid>': unidades}. Devuelve solo a quien le toca algo."""
    cfg = core.clean_assign_config(cfg)
    out = {}
    for u in users:
        dep_rows = []
        if cfg["dep_product"]:
            for p in people_by_holder.get(u["id"], []):
                for r in p["rows"]:
                    dep_rows.append({"uid": r["uid"], "label": p["label"], "name": p["name"], "data": r["data"]})
            for r in own.get(u["id"], []):
                dep_rows.append({"uid": r["uid"], "label": (r["name"] or "Esta persona") + " (dependiente de " + r["holder"] + ")", "name": r["name"], "data": r["data"]})
        lines = core.lines_for(u.get("product"), u.get("qty"), dep_rows, cfg)
        if not lines:
            continue
        res = []
        for ln in lines:
            item = items.get(ln["product_key"])
            done = int(holder_done.get(u["id"], 0)) if ln["key"] == core.HOLDER_KEY else int(dep_done.get(ln["key"], 0))
            pending = max(ln["qty"] - done, 0)
            problem = ln["problem"]
            if item is None and not problem:
                problem = f"«{ln['product']}» no está en el inventario del evento (pide a un coordinador «Actualizar productos desde la base»)"
            available = (item["initial_qty"] - int(stock.get(item["id"], 0))) if item is not None else 0
            res.append({**ln, "item_id": item["id"] if item else None, "item_name": item["name"] if item else ln["product"], "delivered": done, "pending": pending,
                        "available": available, "problem": problem, "done": pending == 0 and ln["qty"] > 0})
        out[u["id"]] = res
    return out
