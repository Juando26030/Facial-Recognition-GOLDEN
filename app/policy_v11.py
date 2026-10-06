"""Política de Privacidad v1.1 en la página pública /privacidad, SIN tocar un byte de docs/legal/POLITICA_v1.1.md.

La auditora ratificó el archivo exacto (SHA-256 abajo, 6 de octubre de 2026). Aquí solo se LEE: se comprueba que el archivo siga siendo ese (si no coincide, la página NO lo muestra y cae a la versión 1.0), se
OMITE al mostrarlo el párrafo de estado de borrador («ESTADO: PENDIENTE DE RATIFICACIÓN…») y las etiquetas «(texto de la auditora)», y se agrega aparte la leyenda de ratificación. Las frases literales de la
auditora (secciones 6, 7 y 8) se muestran tal cual. `POLICY_VERSION=1.1` activa esta versión como vigente (la 1.0 queda como histórica en /privacidad/v1.0); sin esa variable sigue la 1.0.
"""
import hashlib
import html
import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("golden.policy")
RATIFIED_SHA256 = "d0afc7d95083b62115ce001abeb1ab8e86925e35a14d80011e06bf75e253c844"
RATIFIED_ON = "6 de octubre de 2026"
POLICY_FILE = Path("docs/legal/POLITICA_v1.1.md")
_LABEL = " (texto de la auditora)"


def active_version() -> str:
    return "1.1" if os.getenv("POLICY_VERSION", "1.0").strip() == "1.1" else "1.0"


def load_verified() -> Optional[str]:
    """El texto del archivo si es EXACTAMENTE el ratificado; None si falta o cambió (nunca se muestra una política que no es la ratificada)."""
    try:
        raw = POLICY_FILE.read_bytes()
    except OSError:
        log.error("política v1.1: no se encontró el archivo")
        return None
    if hashlib.sha256(raw).hexdigest() != RATIFIED_SHA256:
        log.error("política v1.1: el archivo no coincide con el hash ratificado; no se muestra")
        return None
    return raw.decode("utf-8")


def legend() -> str:
    return f"Ratificada el {RATIFIED_ON} · SHA-256 {RATIFIED_SHA256}"


def _inline(text: str) -> str:
    text = html.escape(text.replace(_LABEL, ""), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(https?://[^\s<)]+[^\s<).,;])", r'<a href="\1">\1</a>', text)
    return re.sub(r"([\w.+-]+@[\w-]+\.[\w.-]+[\w])", r'<a href="mailto:\1">\1</a>', text)


def to_html(markdown: str) -> str:
    """Conversión mínima (títulos, párrafos, listas, tablas, citas, negritas). Omite el párrafo de estado de borrador; no altera ninguna frase."""
    out, para, items, rows, quote = [], [], [], [], []

    def flush():
        nonlocal para, items, rows, quote
        if para:
            out.append("<p>" + "<br>".join(_inline(l) for l in para) + "</p>")      # los saltos de línea del texto (p. ej. la sección 8) se conservan
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
        if rows:
            body = [r for r in rows if not re.fullmatch(r"\|?[\s:|-]+\|?", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in body]
            if cells:
                out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells[0]) + "</tr>" + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in cells[1:]) + "</table>")
        if quote:
            out.append("<blockquote>" + "<br>".join(_inline(q) for q in quote) + "</blockquote>")
        para, items, rows, quote = [], [], [], []

    for line in markdown.replace("\r\n", "\n").split("\n"):
        s = line.rstrip()
        if not s.strip():
            flush()
        elif s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            out.append(f"<h{min(level, 3)}>{_inline(s[level:].strip())}</h{min(level, 3)}>")
        elif s.startswith("**ESTADO:"):
            flush()                                                     # marca de borrador: no se muestra (el archivo no se toca)
        elif s.startswith("- "):
            if para or rows or quote:
                flush()
            items.append(s[2:])
        elif s.startswith("|"):
            if para or items or quote:
                flush()
            rows.append(s)
        elif s.startswith(">"):
            if para or items or rows:
                flush()
            quote.append(s.lstrip("> ").strip())
        else:
            if items or rows or quote:
                flush()
            para.append(s.strip())
    flush()
    return "\n".join(out)
