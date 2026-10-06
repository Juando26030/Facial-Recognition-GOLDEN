"""Datos legales del negocio y del tratamiento de datos, para las páginas públicas (Política de Privacidad, Términos, Reembolsos y pie de página).

NIT y razón social son los de Golden (los que ya constan en Wompi). Lo que aún no se conoce con certeza (dirección, teléfono, plazos) queda como marcador
`[… — completar]` y se puede definir SIN tocar código con variables de entorno: LEGAL_NAME, LEGAL_NIT, LEGAL_ADDRESS, LEGAL_PHONE, LEGAL_EMAIL,
LEGAL_PRIVACY_EMAIL, BIOMETRIC_RETENTION_DAYS_AFTER_EVENT, BIOMETRIC_MAX_DAYS, REFUND_REQUEST_DAYS.
"""
import hashlib
import os
import re
from pathlib import Path

from app import company, privacy

# Textos con CONSTANCIA de revisión legal escrita (la auditora, 2026-10-05): política de privacidad versión 1.0, tal como estaba en staging (revisión 00048, con el apartado 5-bis y Neon y Google como
# encargados). `sha256` = huella del texto de la plantilla SIN los marcadores «pendiente» y con los espacios normalizados (así quitar un marcador no cambia la huella, pero cambiar una palabra sí).
# Si el texto cambia, la huella deja de coincidir y la página vuelve SOLA a «BORRADOR — PENDIENTE DE REVISIÓN LEGAL» (mostrando cuál fue la última versión revisada): subir la versión y pedir
# otra constancia; solo entonces se actualiza la huella. Los demás textos (términos, reembolsos, consentimientos) NO están cubiertos y siguen marcados.
REVIEWED = {
    "privacidad": {"version": "1.0", "date": "5 de octubre de 2026", "template": "templates/legal_privacidad.html",
                   "sha256": "fff49c932a78e7c778ee7906e2100beab4281a250c31d40a29d539a66a63af51"},
}


def text_fingerprint(source: str) -> str:
    source = source.replace("\r\n", "\n")
    source = re.sub(r'<span class="pending">.*?</span>', "", source, flags=re.S)
    source = re.sub(r"\s+", " ", source).strip()
    return hashlib.sha256(re.sub(r"\s*([<>])\s*", r"\1", source).encode("utf8")).hexdigest()      # sin espacios pegados a las etiquetas: quitar un marcador no cambia la huella


def review_status(name: str):
    """None si el texto no tiene constancia; si la tiene: versión, fecha y `reviewed` (False si el texto cambió después de la constancia)."""
    cfg = REVIEWED.get(name)
    if not cfg:
        return None
    current = text_fingerprint(Path(cfg["template"]).read_text(encoding="utf8"))
    return {"version": cfg["version"], "date": cfg["date"], "reviewed": current == cfg["sha256"]}


def info() -> dict:
    email = os.getenv("LEGAL_EMAIL", "info@goldenlogisticas.com")
    days, cap = privacy.days_after_event(), privacy.max_days()
    backup_days = 30            # deploy/gcs-lifecycle.json (respaldos diarios)
    refund = os.getenv("REFUND_REQUEST_DAYS", "").strip()
    return {
        "name": os.getenv("LEGAL_NAME", "GOLDEN EVENTOS Y LOGISTICA SAS"),
        "nit": company.nit_display(os.getenv("COMPANY_NIT") or os.getenv("LEGAL_NIT") or "901542833-2"),
        "address": os.getenv("LEGAL_ADDRESS", "Carrera 14a # 71a - 59, Bogotá, Colombia"),
        "phone": os.getenv("LEGAL_PHONE", "+57 317 427 6073"),
        "email": email,
        "privacy_email": os.getenv("PRIVACY_EMAIL") or os.getenv("LEGAL_PRIVACY_EMAIL") or "soporteit@goldenlogisticas.com",      # PRIVACY_EMAIL es el único correo de privacidad; LEGAL_PRIVACY_EMAIL es un alias OBSOLETO (se lee solo si falta aquella)
        "retention": f"{days} días después de que finalice el evento (si participas en más de un evento, después de que hayan finalizado todos), y en ningún caso más de {cap} días desde que se captura",
        "cap_days": cap, "backup_days": backup_days,
        "refund_days": f"{refund} días calendario" if refund.isdigit() else "el plazo que indique cada formulario",
        "updated": "25 de septiembre de 2026",
    }
