"""Solicitud de cotización del sitio web corporativo (golden-eventos.com): lógica PURA (sin FastAPI ni base de datos).

El sitio estático llama a `POST /api/public/quote-request` (ver app/routers/quote_request.py). El correo que sale es el único registro: no hay tabla.
Aquí viven la validación, el armado del correo y la lista de orígenes permitidos, para poder probarlos sin levantar la aplicación."""
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.inputcheck import check_text

PATH = "/api/public/quote-request"
MAX_BODY_BYTES = 8 * 1024
MAIL_KIND = "quote_mail"
TIPOS = ("Congreso", "Convención", "Asamblea de accionistas", "Junta directiva", "Lanzamiento", "Feria comercial", "Evento académico", "Otro")
MAX_LEN = {"nombre": 100, "empresa": 120, "ciudad": 80, "contacto": 120}
ASISTENTES_MAX = 1_000_000
MSG_UNAVAILABLE = "No se pudo enviar ahora, escríbanos por WhatsApp"
MSG_TOO_MANY = "Demasiados intentos. Espere unos minutos o escríbanos por WhatsApp"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-']{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^[+(]?[0-9][0-9 ()\-]{5,22}$")


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL.match((value or "").strip()))


def _looks_like_phone(value: str) -> bool:
    v = (value or "").strip()
    return bool(_PHONE.match(v)) and 7 <= sum(c.isdigit() for c in v) <= 15


def allowed_origins(raw: Optional[str] = None) -> List[str]:
    """Orígenes (esquema + host, sin barra final) que pueden llamar a esta ruta desde otro dominio. Vacío = solo mismo origen."""
    raw = os.getenv("QUOTE_ALLOWED_ORIGINS", "") if raw is None else raw
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]


def origin_allowed(origin: Optional[str], raw: Optional[str] = None) -> bool:
    return bool(origin) and origin in allowed_origins(raw)


def cors_headers(origin: Optional[str], raw: Optional[str] = None) -> Dict[str, str]:
    """Cabeceras mínimas: el origen EXACTO permitido (nunca «*»), solo POST y Content-Type. Sin cookies (no hay Allow-Credentials)."""
    if not origin_allowed(origin, raw):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "600", "Vary": "Origin"}


def _text(data: dict, key: str, label: str, errors: Dict[str, str], required: bool) -> str:
    raw = data.get(key)
    if raw is None or raw == "":
        if required:
            errors[key] = f"{label} es {'obligatoria' if label.startswith('La ') else 'obligatorio'}"
        return ""
    if not isinstance(raw, str):
        errors[key] = f"{label} no es válido"
        return ""
    value = re.sub(r"\s+", " ", raw).strip() if key != "contacto" else raw.strip()
    if not value:
        if required:
            errors[key] = f"{label} es {'obligatoria' if label.startswith('La ') else 'obligatorio'}"
        return ""
    if len(value) > MAX_LEN[key]:
        errors[key] = f"{label} es muy largo (máximo {MAX_LEN[key]} caracteres)"
        return ""
    try:
        check_text(raw, label)
    except ValueError:
        errors[key] = f"{label} no puede incluir «<», «>» ni caracteres de control"
        return ""
    return value


def validate(data) -> Tuple[Dict[str, object], Dict[str, str]]:
    """(datos limpios, errores por campo). Con errores, los datos no deben usarse."""
    errors: Dict[str, str] = {}
    if not isinstance(data, dict):
        return {}, {"_": "El envío no es válido"}
    out: Dict[str, object] = {
        "nombre": _text(data, "nombre", "El nombre", errors, True),
        "empresa": _text(data, "empresa", "La empresa", errors, False),
        "ciudad": _text(data, "ciudad", "La ciudad", errors, True),
        "contacto": _text(data, "contacto", "El correo o celular", errors, True),
    }
    if out["contacto"] and "contacto" not in errors and not (looks_like_email(str(out["contacto"])) or _looks_like_phone(str(out["contacto"]))):
        errors["contacto"] = "Escriba un correo válido o un celular con indicativo, por ejemplo 3001234567"
    tipo = data.get("tipo")
    if tipo in (None, ""):
        errors["tipo"] = "Elija el tipo de evento"
    elif not isinstance(tipo, str) or tipo.strip() not in TIPOS:
        errors["tipo"] = "Elija un tipo de evento de la lista"
    else:
        out["tipo"] = tipo.strip()
    fecha = data.get("fecha")
    if fecha in (None, ""):
        out["fecha"] = ""
    else:
        try:
            if not isinstance(fecha, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha.strip()):
                raise ValueError
            datetime.strptime(fecha.strip(), "%Y-%m-%d")
            out["fecha"] = fecha.strip()
        except ValueError:
            errors["fecha"] = "La fecha debe tener el formato AAAA-MM-DD, por ejemplo 2027-03-15"
    n = data.get("asistentes")
    if isinstance(n, str) and re.fullmatch(r"\d{1,8}", n.strip()):
        n = int(n.strip())
    if n in (None, ""):
        errors["asistentes"] = "Indique cuántas personas asistirán"
    elif isinstance(n, bool) or not isinstance(n, int) or not (1 <= n <= ASISTENTES_MAX):
        errors["asistentes"] = f"El número de asistentes debe ser un entero entre 1 y {ASISTENTES_MAX:,}".replace(",", ".")
    else:
        out["asistentes"] = n
    return out, errors


def build_mail(clean: dict) -> dict:
    """Asunto, cuerpo de texto plano y Reply-To (solo si el contacto es un correo)."""
    contacto = str(clean["contacto"])
    lines = [
        "Nueva solicitud de cotización desde el sitio web.", "",
        f"Nombre: {clean['nombre']}",
        f"Empresa: {clean.get('empresa') or '(no indicada)'}",
        f"Tipo de evento: {clean['tipo']}",
        f"Fecha tentativa: {clean.get('fecha') or '(no indicada)'}",
        f"Ciudad: {clean['ciudad']}",
        f"Asistentes: {clean['asistentes']}",
        f"Contacto: {contacto}",
    ]
    return {"subject": f"Nueva solicitud de cotización · {clean['tipo']} · {clean['ciudad']}", "text": "\n".join(lines) + "\n",
            "reply_to": contacto if looks_like_email(contacto) else None}
