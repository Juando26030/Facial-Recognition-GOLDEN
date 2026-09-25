"""Datos legales del negocio y del tratamiento de datos, para las páginas públicas (Política de Privacidad, Términos, Reembolsos y pie de página).

NIT y razón social son los de Golden (los que ya constan en Wompi). Lo que aún no se conoce con certeza (dirección, teléfono, plazos) queda como marcador
`[… — completar]` y se puede definir SIN tocar código con variables de entorno: LEGAL_NAME, LEGAL_NIT, LEGAL_ADDRESS, LEGAL_PHONE, LEGAL_EMAIL,
LEGAL_PRIVACY_EMAIL, BIOMETRIC_RETENTION_DAYS, REFUND_REQUEST_DAYS.
"""
import os


def info() -> dict:
    email = os.getenv("LEGAL_EMAIL", "info@goldenlogisticas.com")
    days = os.getenv("BIOMETRIC_RETENTION_DAYS", "").strip()
    refund = os.getenv("REFUND_REQUEST_DAYS", "").strip()
    return {
        "name": os.getenv("LEGAL_NAME", "GOLDEN EVENTOS Y LOGISTICA SAS"),
        "nit": os.getenv("LEGAL_NIT", "901542833"),
        "address": os.getenv("LEGAL_ADDRESS", "[DIRECCIÓN — completar]"),
        "phone": os.getenv("LEGAL_PHONE", "[TELÉFONO — completar]"),
        "email": email,
        "privacy_email": os.getenv("LEGAL_PRIVACY_EMAIL", email),
        "retention": f"{days} días después de la fecha de finalización del evento" if days.isdigit() else "[PLAZO DE RETENCIÓN — pendiente de definir por Golden]",
        "refund_days": f"{refund} días calendario" if refund.isdigit() else "[PLAZO — pendiente de definir por Golden]",
        "updated": "25 de septiembre de 2026",
    }
