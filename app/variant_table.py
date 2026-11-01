"""Tabla de variantes (P11): plantilla y lectura de .xlsx. Lógica pura (sin base ni HTTP); la usan los endpoints de `routers/forms.py`.

SEGURIDAD (el archivo lo sube una persona y no se le puede tener confianza):
- Solo `.xlsx`, hasta 2 MB; se procesa EN MEMORIA: no se guarda en disco ni en el almacenamiento.
- Antes de abrirlo se revisa el zip: tamaño descomprimido total y por parte (anti zip-bomb), razón de compresión, cantidad de partes, y se rechazan macros,
  vínculos externos, objetos incrustados y cualquier XML con DOCTYPE/ENTITY. Después se lee con openpyxl en modo solo lectura, sin vínculos, con `defusedxml` en uso
  (dependencia obligada: sin ella se rechaza todo) y SIN calcular nada: una celda con fórmula rechaza el archivo.
- Solo se leen las primeras 500 filas; una hoja que declara dimensiones enormes se rechaza.
- Al GENERAR el Excel, todo texto que empiece con = + - @ (o tabulador / retorno) se escribe como texto (tipo de celda texto y prefijo de comilla): Excel nunca lo evalúa.
- Nada del contenido de las celdas se escribe en logs ni en los mensajes de error."""
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import openpyxl
import openpyxl.xml
from openpyxl.styles import Alignment, Font

from app.formlib import norm_value

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED = 20 * 1024 * 1024          # suma de todas las partes ya descomprimidas
MAX_PART = 10 * 1024 * 1024                  # una sola parte
MAX_RATIO = 100                              # descomprimido / comprimido de una parte
MAX_PARTS = 200
MAX_READ_ROWS = 500
DECLARED_ROWS_LIMIT = 5000                   # una hoja que DECLARA más filas o columnas no se abre
DECLARED_COLS_LIMIT = 100
MAX_ROWS, MAX_COLS, MAX_VARS, MAX_TEXT = 200, 15, 3, 8000
TYPES = ("text", "image", "date", "number", "options")
_IMG = re.compile(r".+\.(png|jpe?g|webp|gif)$", re.I)
_IMG_PATH = re.compile(r"[A-Za-z0-9_-][\w.-]*/[A-Za-z0-9_-][\w.-]*\.(?:png|jpe?g|webp|gif)")
_DANGEROUS_PARTS = re.compile(r"(^|/)(vbaProject\.bin|externalLinks/|embeddings/|activeX/|macrosheets/|dialogsheets/|customUI/|oleObject)|\.bin$", re.I)


class ExcelRejected(ValueError):
    """El archivo no se acepta; el mensaje (en español) se muestra tal cual y nunca incluye contenido de las celdas."""


# ------------------------------------------------------------------ celdas (mismas reglas y casos que static/js/variant-table.js, ver tests/variant_cell_vectors.json)
def _fmt_date(d: int, m: int, y: int) -> Optional[str]:
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        date(y, m, d)
    except ValueError:
        return None
    return f"{d:02d}/{m:02d}/{y}"


def _parse_number(raw: str) -> Optional[str]:
    t = re.sub(r"\s", "", raw)
    neg = t.startswith("-")
    if neg or t.startswith("+"):
        t = t[1:]
    if not re.fullmatch(r"[\d.,]+", t) or not re.search(r"\d", t):
        return None
    frac = ""
    last_dot, last_comma = t.rfind("."), t.rfind(",")
    if last_dot >= 0 and last_comma >= 0:                # los dos: el ÚLTIMO separador es el decimal
        dec = max(last_dot, last_comma)
        dec_ch, other = ("." if dec == last_dot else ","), ("," if dec == last_dot else ".")
        integer, frac = t[:dec], t[dec + 1:]
        if dec_ch in integer:
            return None
        integer = integer.replace(other, "")
        if not re.fullmatch(r"\d+", integer) or not re.fullmatch(r"\d*", frac):
            return None
    elif last_comma >= 0:                                # solo comas: la coma es el decimal (formato colombiano)
        if t.count(",") > 1:
            return None
        integer, frac = t.split(",")
        if not re.fullmatch(r"\d+", integer) or not re.fullmatch(r"\d*", frac):
            return None
    elif last_dot >= 0:                                  # solo puntos: «1.234» y «1.234.567» son miles; «12.5» es un decimal
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
            integer = t.replace(".", "")
        elif re.fullmatch(r"\d+\.\d+", t):
            integer, frac = t.split(".")
        else:
            return None
    else:
        integer = t
    if len(integer) > 15 or len(frac) > 8:
        return None
    integer = re.sub(r"^0+(?=\d)", "", integer)
    grouped = re.sub(r"\B(?=(\d{3})+(?!\d))", ".", integer)
    return ("-" if neg and (integer != "0" or re.search(r"[1-9]", frac)) else "") + grouped + ("," + frac if frac else "")


def parse_cell(kind: str, raw, options: Optional[list] = None):
    """(valor, error). Valor '' = celda vacía (no genera variante). Acepta también los tipos nativos de Excel (fechas, números)."""
    if isinstance(raw, (datetime, date)):
        raw = f"{raw.day:02d}/{raw.month:02d}/{raw.year}"
    elif isinstance(raw, bool):
        raw = ""
    elif isinstance(raw, (int, float, Decimal)) and kind in ("number", "text", "options"):
        raw = format(Decimal(str(raw)).normalize(), "f") if not isinstance(raw, int) else str(raw)
    t = str("" if raw is None else raw).strip()
    if not t:
        return "", None
    if kind == "text":
        return (t, None) if len(t) <= MAX_TEXT else ("", f"El texto es demasiado largo (máximo {MAX_TEXT} caracteres)")
    if kind == "date":
        m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})", t)
        v = _fmt_date(int(m[1]), int(m[2]), int(m[3])) if m else None
        if not v and (m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)):
            v = _fmt_date(int(m[3]), int(m[2]), int(m[1]))
        return (v, None) if v else ("", "Fecha no válida (escribe dd/mm/aaaa)")
    if kind == "number":
        v = _parse_number(t)
        return (v, None) if v else ("", "Número no válido (ejemplo: 1.234,56)")
    if kind == "options":
        hit = next((o for o in (options or []) if norm_value(o) == norm_value(t)), None)
        return (hit, None) if hit else ("", "No está en la lista de opciones")
    if kind == "image":
        ok = (_IMG.fullmatch(t) and not re.search(r"[\\/]", t) and not t.startswith(".")) or _IMG_PATH.fullmatch(t)
        return (t, None) if ok else ("", "Usa un archivo PNG, JPG, WEBP o GIF")
    return "", "Tipo de columna desconocido"


# ------------------------------------------------------------------ la definición de la tabla que manda el navegador
def validate_spec(spec) -> dict:
    """Revisa la forma y los topes de {variables: [{label, options}], columns: [{id, name, type, options?}], rows: [{keys, cells?}]}."""
    if not isinstance(spec, dict):
        raise ExcelRejected("La definición de la tabla no es válida")
    variables, columns, rows = spec.get("variables"), spec.get("columns"), spec.get("rows")
    if not isinstance(variables, list) or not 1 <= len(variables) <= MAX_VARS:
        raise ExcelRejected(f"Elige de 1 a {MAX_VARS} campos que decidan")
    if not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLS:
        raise ExcelRejected(f"La tabla admite de 1 a {MAX_COLS} columnas")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ExcelRejected(f"La tabla admite hasta {MAX_ROWS} filas")
    names = set()
    for v in variables:
        if not isinstance(v, dict) or not str(v.get("label") or "").strip() or not isinstance(v.get("options", []), list):
            raise ExcelRejected("Cada campo que decide necesita un nombre")
        if v.get("field") is not None and not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(v["field"])):
            raise ExcelRejected("Un campo que decide no es válido")
        names.add(norm_value(v["label"]))
    ids = set()
    for c in columns:
        if not isinstance(c, dict) or c.get("type") not in TYPES or not str(c.get("name") or "").strip() or not re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(c.get("id") or "")) or c["id"] in ids:
            raise ExcelRejected("Una columna no es válida")
        ids.add(c["id"])
        key = norm_value(c["name"])
        if key in names:
            raise ExcelRejected("Dos columnas tienen el mismo nombre")
        names.add(key)
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("keys"), list) or len(r["keys"]) != len(variables):
            raise ExcelRejected("Una fila de la tabla no es válida")
    return spec


# ------------------------------------------------------------------ generar el Excel
def _put(ws, row: int, col: int, value, bold: bool = False):
    """Escribe SIEMPRE como texto cuando es un string: si empieza con = + - @ tabulador o retorno, Excel no puede tomarlo por una fórmula."""
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        cell.value = value
        cell.data_type = "s"
        cell.number_format = "@"
        if value[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
            cell.quotePrefix = True
    else:
        cell.value = value
    if bold:
        cell.font = Font(bold=True)
    return cell


def build_template(spec: dict) -> bytes:
    spec = validate_spec(spec)
    variables, columns, rows = spec["variables"], spec["columns"], spec["rows"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tabla"
    heads = [v["label"] for v in variables] + [c["name"] for c in columns]
    for j, h in enumerate(heads, start=1):
        _put(ws, 1, j, str(h)[:200], bold=True)
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = 22 if j <= len(variables) else 34
    for i, r in enumerate(rows, start=2):
        for j, k in enumerate(r["keys"], start=1):
            _put(ws, i, j, str(k))
        for j, c in enumerate(columns, start=len(variables) + 1):
            v = (r.get("cells") or {}).get(c["id"])
            if v not in (None, ""):
                _put(ws, i, j, str(v)[:MAX_TEXT])
    ws.freeze_panes = ws.cell(row=2, column=len(variables) + 1)
    info = wb.create_sheet("Instrucciones")
    lines = [
        "Tabla de variantes", "",
        f"1. En la hoja «Tabla» llena las columnas de la derecha. Cada fila es una combinación de {', '.join(str(v['label']) for v in variables)}.",
        "2. No cambies los valores de las primeras columnas ni el nombre de los encabezados: así se reconoce cada fila. Puedes borrar filas que no necesites.",
        "3. Una celda vacía no crea variante: esa combinación usa el valor por defecto.",
        "4. Fechas: dd/mm/aaaa (también dd/mm/aa o aaaa-mm-dd). Números: con coma decimal y punto de miles, por ejemplo 1.234,56.",
        "5. Imágenes: escribe el nombre del archivo (por ejemplo bogota.jpg) y súbelo en la pantalla; no se puede pegar la imagen aquí.",
        "6. Texto con formato: escribe el texto aquí y dale formato después en la pantalla de la tabla.",
        "7. No uses fórmulas, macros ni vínculos: el archivo se rechaza. Guárdalo como .xlsx (máximo 2 MB, hasta 500 filas).",
        "8. Los valores válidos de cada lista están en la hoja «Valores válidos».", "",
        "Columnas:",
    ]
    tipo = {"text": "texto", "image": "imagen (nombre del archivo)", "date": "fecha dd/mm/aaaa", "number": "número 1.234,56", "options": "una de las opciones de la lista"}
    lines += [f"   • {c['name']}: {tipo[c['type']]}" for c in columns]
    for i, line in enumerate(lines, start=1):
        _put(info, i, 1, line, bold=(i == 1))
    info.column_dimensions["A"].width = 120
    for row in info.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    # Hoja oculta con la identidad de cada columna (por id, no por nombre): renombrar un elemento o reordenar las columnas no rompe la subida del archivo.
    meta = wb.create_sheet("_meta")
    _put(meta, 1, 1, json.dumps({"v": 1, "vars": [{"h": str(v["label"]), "field": v.get("field")} for v in variables], "cols": [{"h": str(c["name"]), "id": c["id"]} for c in columns]}, ensure_ascii=False))
    meta.sheet_state = "veryHidden"
    vals = wb.create_sheet("Valores válidos")
    lists = [(str(v["label"]), v.get("options") or []) for v in variables] + [(c["name"], c.get("options") or []) for c in columns if c["type"] == "options"]
    for j, (title, options) in enumerate(lists, start=1):
        _put(vals, 1, j, str(title)[:200], bold=True)
        vals.column_dimensions[openpyxl.utils.get_column_letter(j)].width = 28
        for i, o in enumerate(options[:2000], start=2):
            _put(vals, i, j, str(o)[:300])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ leer el Excel
def check_archive(data: bytes, filename: str) -> None:
    """Todas las defensas que NO dependen de openpyxl; lanza ExcelRejected."""
    if not (filename or "").lower().endswith(".xlsx"):
        raise ExcelRejected("Sube un archivo .xlsx (no se aceptan .xls, .xlsm ni .csv)")
    if len(data) > MAX_FILE_BYTES:
        raise ExcelRejected("El archivo pesa más de 2 MB")
    if not data.startswith(b"PK"):
        raise ExcelRejected("El archivo no es un Excel (.xlsx) válido")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ExcelRejected("El archivo no es un Excel (.xlsx) válido")
    if len(infos) > MAX_PARTS:
        raise ExcelRejected("El archivo tiene demasiadas partes")
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > MAX_PART or total > MAX_UNCOMPRESSED:
            raise ExcelRejected("El archivo es demasiado grande una vez descomprimido")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1_000_000:
            raise ExcelRejected("El archivo está comprimido de forma sospechosa")
        if _DANGEROUS_PARTS.search(info.filename) or info.filename.startswith(("/", "..")) or ".." in info.filename.split("/"):
            raise ExcelRejected("El archivo trae macros, vínculos externos u objetos incrustados: no se acepta")
    names = {i.filename for i in infos}
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise ExcelRejected("El archivo no es un Excel (.xlsx) válido")
    for info in infos:
        if info.filename.endswith((".xml", ".rels")):
            with zf.open(info) as fh:
                body = fh.read(MAX_PART + 1)
            if len(body) > MAX_PART:
                raise ExcelRejected("El archivo es demasiado grande una vez descomprimido")
            low = body.lower()
            if b"<!doctype" in low or b"<!entity" in low:
                raise ExcelRejected("El archivo contiene definiciones XML no permitidas")
            if info.filename == "[Content_Types].xml" and (b"macroenabled" in low or b"vbaproject" in low):
                raise ExcelRejected("El archivo trae macros: no se acepta")


def _cell_text(cell):
    """Valor de una celda leída; rechaza fórmulas. Devuelve (valor, error)."""
    if cell.data_type == "f":
        raise ExcelRejected("El archivo tiene fórmulas: pega solo valores (no se ejecuta ninguna fórmula)")
    if cell.data_type == "e":
        return None, "La celda tiene un error de Excel"
    return cell.value, None


def _read_meta(wb) -> dict:
    """La hoja oculta `_meta` del archivo (si la trae): {encabezado normalizado: id de columna / de campo}. Es texto de un archivo ajeno: solo se usa para BUSCAR ids que ya existen en la definición."""
    out = {"vars": {}, "cols": {}}
    if "_meta" not in wb.sheetnames:
        return out
    try:
        first = next(wb["_meta"].iter_rows(min_row=1, max_row=1, max_col=1), None)
        if not first:
            return out
        raw, _ = _cell_text(first[0])
        if not isinstance(raw, str) or len(raw) > 20000:
            return out
        d = json.loads(raw)
        for item in (d.get("vars") or [])[:MAX_VARS]:
            if isinstance(item, dict) and isinstance(item.get("h"), str) and isinstance(item.get("field"), str):
                out["vars"][norm_value(item["h"])] = item["field"]
        for item in (d.get("cols") or [])[:MAX_COLS]:
            if isinstance(item, dict) and isinstance(item.get("h"), str) and isinstance(item.get("id"), str):
                out["cols"][norm_value(item["h"])] = item["id"]
    except ExcelRejected:
        raise
    except Exception:
        return {"vars": {}, "cols": {}}
    return out


def read_table(data: bytes, filename: str, spec: dict, mapping: Optional[dict] = None, ask: bool = False) -> dict:
    """Lee la hoja «Tabla» (o la primera) y la empareja con la definición. No guarda nada. Devuelve
    {rows: [{keys, cells}], problems: [{row, col, message}], unmatched_rows, duplicated_rows, ignored_columns, missing_rows}.
    `mapping` ({encabezado: "ignore" | "v<i>" | "c:<id de columna>"}) lo manda el paso «Asignar columnas» y vale solo para esta lectura. Con `ask`, si algún encabezado no coincide con una columna
    (por id de la hoja oculta ni por nombre) NO se lee nada y se devuelve {needs_mapping: True, headers: [{header, suggested}]} para que la persona asigne."""
    spec = validate_spec(spec)
    if not getattr(openpyxl.xml, "DEFUSEDXML", False):
        raise ExcelRejected("El servidor no puede leer archivos de Excel de forma segura (falta defusedxml)")
    check_archive(data, filename)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except ExcelRejected:
        raise
    except Exception:                                    # XML mal formado, entidades prohibidas, zip raro…: nunca se detalla (podría incluir contenido)
        raise ExcelRejected("El archivo no se pudo leer como Excel (.xlsx)")
    try:
        ws = wb["Tabla"] if "Tabla" in wb.sheetnames else wb[wb.sheetnames[0]]
        if (ws.max_row or 0) > DECLARED_ROWS_LIMIT or (ws.max_column or 0) > DECLARED_COLS_LIMIT:
            raise ExcelRejected("La hoja es demasiado grande (el máximo son 500 filas de datos)")
        meta = _read_meta(wb)
        lines = []
        for r, row in enumerate(ws.iter_rows(min_row=1, max_row=MAX_READ_ROWS + 2, max_col=DECLARED_COLS_LIMIT), start=1):
            vals = []
            for cell in row:
                v, err = _cell_text(cell)
                vals.append((v, err))
            lines.append(vals)
    except ExcelRejected:
        raise
    except Exception:
        raise ExcelRejected("El archivo no se pudo leer como Excel (.xlsx)")
    finally:
        wb.close()
    while lines and all(v in (None, "") and not e for v, e in lines[-1]):
        lines.pop()
    if not lines:
        raise ExcelRejected("La hoja está vacía")
    if len(lines) > MAX_READ_ROWS + 1:
        raise ExcelRejected(f"La hoja tiene más de {MAX_READ_ROWS} filas de datos")
    variables, columns = spec["variables"], spec["columns"]
    heads = [norm_value(v) if v is not None else "" for v, _ in lines[0]]
    texts = [("" if v is None else str(v)) for v, _ in lines[0]]
    # Cada encabezado se reconoce primero por la identidad que trae la hoja oculta (id del campo / de la columna) y, si no, por su nombre.
    def find_var(v):
        by_id = [j for j, h in enumerate(heads) if v.get("field") and meta["vars"].get(h) == v["field"]]
        by_name = [j for j, h in enumerate(heads) if h == norm_value(v["label"])]
        return (by_id or by_name or [None])[0]

    def find_col(c):
        by_id = [j for j, h in enumerate(heads) if h and meta["cols"].get(h) == c["id"]]
        by_name = [j for j, h in enumerate(heads) if h == norm_value(c["name"])]
        return (by_id or by_name or [None])[0]
    if mapping is None:
        key_at = [find_var(v) for v in variables]
        col_at = {c["id"]: j for c in columns if (j := find_col(c)) is not None}
        used = set(j for j in key_at if j is not None) | set(col_at.values())
        unresolved = [j for j, h in enumerate(heads) if h and j not in used]
        if ask and (unresolved or any(j is None for j in key_at)):
            targets = {j: f"v{i}" for i, j in enumerate(key_at) if j is not None}
            targets.update({j: f"c:{cid}" for cid, j in col_at.items()})
            return {"needs_mapping": True, "headers": [{"header": texts[j][:80], "suggested": targets.get(j)} for j, h in enumerate(heads) if h][:60]}
        if any(j is None for j in key_at):
            raise ExcelRejected("Falta en la primera fila una columna de los campos que deciden: usa la plantilla")
    else:                                          # asignación explícita de la persona: solo vale para esta lectura
        if not isinstance(mapping, dict) or len(mapping) > 200:
            raise ExcelRejected("La asignación de columnas no es válida")
        valid = {f"v{i}" for i in range(len(variables))} | {f"c:{c['id']}" for c in columns} | {"ignore"}
        chosen = {}
        for j, text in enumerate(texts):
            if not heads[j]:
                continue
            target = mapping.get(text, "ignore")
            if not isinstance(target, str) or target not in valid:
                raise ExcelRejected("La asignación de columnas no es válida")
            if target != "ignore":
                if target in chosen:
                    raise ExcelRejected("Dos columnas del Excel se asignaron al mismo destino")
                chosen[target] = j
        key_at = [chosen.get(f"v{i}") for i in range(len(variables))]
        if any(j is None for j in key_at):
            raise ExcelRejected("Asigna también las columnas de los campos que deciden (son las que identifican cada fila)")
        col_at = {c["id"]: chosen[f"c:{c['id']}"] for c in columns if f"c:{c['id']}" in chosen}
        used = set(key_at) | set(col_at.values())
    ignored = [texts[j][:60] for j, h in enumerate(heads) if h and j not in used][:20]
    index = {tuple(norm_value(k) for k in r["keys"]): i for i, r in enumerate(spec["rows"])}
    out_rows = [{"keys": list(r["keys"]), "cells": {}} for r in spec["rows"]]
    problems, unmatched, duplicated, seen = [], [], [], set()
    for n, line in enumerate(lines[1:], start=2):
        keys = tuple(norm_value("" if line[j][0] is None else line[j][0]) if j < len(line) else "" for j in key_at)
        if not any(keys):
            continue
        at = index.get(keys)
        if at is None:
            unmatched.append(n)
            continue
        if at in seen:
            duplicated.append(n)
            continue
        seen.add(at)
        for c in columns:
            j = col_at.get(c["id"])
            if j is None or j >= len(line):
                continue
            raw, err = line[j]
            if err:
                problems.append({"row": at, "col": c["id"], "message": err})
                continue
            value, err = parse_cell(c["type"], raw, c.get("options"))
            if err:
                problems.append({"row": at, "col": c["id"], "message": err})
            elif value:
                out_rows[at]["cells"][c["id"]] = value
    return {"rows": out_rows, "matched_rows": sorted(seen), "problems": problems, "unmatched_rows": unmatched, "duplicated_rows": duplicated, "ignored_columns": ignored, "missing_rows": len(spec["rows"]) - len(seen)}
