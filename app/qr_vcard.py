"""QR en formato vCard (Fase 10, bloque C): misma lógica que static/js/vcard.js (las pruebas comparan ambas con los mismos casos).

El QR de la escarapela impresa, de la credencial digital y del pase de Wallet es una vCard (nombre y, si vienen con valor: empresa, cargo/rol, teléfono, correo y categorías) con el código de siempre en NOTE
(`NOTE:GW:<código>`), para que el celular pueda guardar el contacto al escanear. El servidor acepta las dos formas: la vCard y el texto anterior (cédula|nombre|apellido o «gwq1…»).
Módulo PURO (sin base de datos)."""
import re
from typing import Optional

PREFIX = "GW:"
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")
_NOTE_LINE = re.compile(r"^NOTE(?:;[^:\n]*)?:GW:(.*)$", re.IGNORECASE | re.MULTILINE)
_NOTE_FLAT = re.compile(r"NOTE:GW:([\s\S]*?)\s*END:VCARD", re.IGNORECASE)


def _esc(v) -> str:
    s = re.sub(r"\s+", " ", _CTRL.sub(" ", str(v if v is not None else ""))).strip()
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def _unesc(v: str) -> str:
    return re.sub(r"\\([\\,;nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def build(first_name="", last_name="", phone="", note="", email="", org="", title="", categories="") -> str:
    first, last = str(first_name or "").strip(), str(last_name or "").strip()
    full = " ".join(x for x in (first, last) if x) or "Asistente"
    tel = re.sub(r"[^\d+()\-.\s]", "", str(phone or "")).strip()
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{_esc(last)};{_esc(first)};;;", f"FN:{_esc(full)}"]
    if org and str(org).strip():
        lines.append(f"ORG:{_esc(org)}")
    if title and str(title).strip():
        lines.append(f"TITLE:{_esc(title)}")
    if tel:
        lines.append(f"TEL:{_esc(tel)}")
    mail = str(email or "").strip()
    if mail and "@" in mail:
        lines.append(f"EMAIL:{_esc(mail)}")
    cats = [c.strip() for c in str(categories or "").split(",") if c.strip()]
    if cats:
        lines.append("CATEGORIES:" + ",".join(_esc(c) for c in cats))
    lines += [f"NOTE:{PREFIX}{_esc(note)}", "END:VCARD"]
    return "\n".join(lines)


def is_vcard(text) -> bool:
    return bool(re.match(r"\s*BEGIN:VCARD", str(text or ""), re.IGNORECASE))


def unwrap(text) -> str:
    """El código de adentro si es una vCard de Golden; si no, el MISMO texto."""
    raw = str(text if text is not None else "")
    if not is_vcard(raw):
        return raw
    t = re.sub(r"\n[ \t]", "", raw.strip().replace("\r\n", "\n").replace("\r", "\n"))
    m: Optional[re.Match] = _NOTE_LINE.search(t) or _NOTE_FLAT.search(t)
    if not m:
        return raw
    return _unesc(re.sub(r"END:VCARD\s*$", "", m.group(1), flags=re.IGNORECASE)).strip()
