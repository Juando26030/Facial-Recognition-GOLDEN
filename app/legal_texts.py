"""Pantalla de autorización biométrica (L1): arma el texto LITERAL de la auditora (app/legal_texts_data.py) para un evento, reemplazando solo las variables.

Devuelve el texto exacto que ve la persona y su SHA-256 (lo que se guarda en `audit_consent_logs.legal_text_hash`). SIN CONSTANCIA hasta que la auditora emita la suya.
"""
import re
from typing import Optional

from app import company, consent
from app.legal_texts_data import SIN_CONSTANCIA, TEXT_PROPIO, TEXT_TERCERO  # noqa: F401  (SIN_CONSTANCIA: marca visible en el código)
from app.models import Event

VERSION_PROPIO, VERSION_TERCERO, VERSION_WEB, VERSION_CLICK = "v1.1_kiosk_propio", "v1.1_kiosk_tercero", "v1.1_web", "v1.1_kiosk_clic"
ADULT_CHECKBOX = "Declaro bajo la gravedad de juramento que tengo 18 años o más"       # casilla aparte SOLO en la variante 1 (el texto A de la auditora no trae la declaración)
EVERY_SCAN_QUESTION = "¿Deseas ingresar mediante reconocimiento facial voluntario?"
EVERY_SCAN_YES, EVERY_SCAN_NO = "SÍ, USAR ROSTRO", "NO, PREFIERO DIGITAR CÉDULA"
_BUTTON = re.compile(r"^\[ BOTÓN (\d): (.+?) \]$", re.M)


def controller_mode(event: Event) -> str:
    return "tercero" if getattr(event, "controller_mode", "golden") == "tercero" else "golden"


def _variables(event: Event) -> dict:
    golden = f"{company.get('COMPANY_NAME')} / {company.get('COMPANY_NIT')}"
    return {
        "[Razón Social de Golden / NIT]": golden,
        "[Razón Social del Organizador / NIT]": f"{event.organizer_name or '[organizer_name]'} / {event.organizer_nit or '[organizer_nit]'}",
        "[Nombre del Evento]": event.name,
        "[correo del organizador]": event.organizer_privacy_email or "[organizer_privacy_email]",
        "[correo de privacidad de Golden]": company.get("PRIVACY_EMAIL"),
        "[URL de la política]": company.policy_url(),
    }


def render(event: Event, web: bool = False) -> dict:
    """{version, variant, text, hash, title, body (párrafos), buttons [b1, b2], adult_checkbox (str|None), blocked (marcadores sin resolver en producción)}."""
    tercero = controller_mode(event) == "tercero"
    text = TEXT_TERCERO if tercero else TEXT_PROPIO
    for k, v in _variables(event).items():
        text = text.replace(k, v)
    lines = text.split("\n")
    buttons = {m.group(1): m.group(2) for m in _BUTTON.finditer(text)}
    body = [p.strip() for p in "\n".join(l for l in lines[1:] if not _BUTTON.match(l)).split("\n\n") if p.strip()]
    return {"version": VERSION_WEB if web else (VERSION_TERCERO if tercero else VERSION_PROPIO), "variant": "tercero" if tercero else "golden", "text": text,
            "hash": consent.text_hash(text), "title": lines[0], "body": body, "buttons": [buttons["1"], buttons["2"]],
            "adult_checkbox": ADULT_CHECKBOX if tercero else None, "blocked": company.blocked(text), "sin_constancia": SIN_CONSTANCIA}


def every_scan_prompt() -> dict:
    """Texto corto de `CONSENT_PROMPT_MODE=every_scan` (antes de cada uso; no sustituye la autorización completa)."""
    return {"question": EVERY_SCAN_QUESTION, "yes": EVERY_SCAN_YES, "no": EVERY_SCAN_NO}


def validate_event_config(controller: str, organizer_name: Optional[str], organizer_nit: Optional[str], organizer_email: Optional[str]) -> Optional[str]:
    if controller not in ("golden", "tercero"):
        return "El tipo de responsable debe ser «golden» o «tercero»"
    if controller == "tercero" and not all((v or "").strip() for v in (organizer_name, organizer_nit, organizer_email)):
        return "En un evento de un tercero se necesitan la razón social, el NIT y el correo de privacidad del organizador"
    return None
