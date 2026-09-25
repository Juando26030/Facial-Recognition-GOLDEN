"""Datos legales del negocio y del tratamiento de datos, para las páginas públicas (Política de Privacidad, Términos, Reembolsos y pie de página).

NIT y razón social son los de Golden (los que ya constan en Wompi). Lo que aún no se conoce con certeza (dirección, teléfono, plazos) queda como marcador
`[… — completar]` y se puede definir SIN tocar código con variables de entorno: LEGAL_NAME, LEGAL_NIT, LEGAL_ADDRESS, LEGAL_PHONE, LEGAL_EMAIL,
LEGAL_PRIVACY_EMAIL, BIOMETRIC_RETENTION_DAYS, REFUND_REQUEST_DAYS.
"""
import os

from app import privacy


def info() -> dict:
    email = os.getenv("LEGAL_EMAIL", "info@goldenlogisticas.com")
    days = privacy.retention_days()
    refund = os.getenv("REFUND_REQUEST_DAYS", "").strip()
    return {
        "name": os.getenv("LEGAL_NAME", "GOLDEN EVENTOS Y LOGISTICA SAS"),
        "nit": os.getenv("LEGAL_NIT", "901542833"),
        "address": os.getenv("LEGAL_ADDRESS", "Carrera 14a # 71a - 59, Bogotá, Colombia"),
        "phone": os.getenv("LEGAL_PHONE", "+57 317 427 6073"),
        "email": email,
        "privacy_email": os.getenv("LEGAL_PRIVACY_EMAIL", email),
        "retention": (f"{days // 30} meses ({days} días) después de la fecha de finalización del evento" if days % 30 == 0 else f"{days} días después de la fecha de finalización del evento") if days else "hasta que solicites su supresión o el Organizador lo borre",
        "refund_days": f"{refund} días calendario" if refund.isdigit() else "el plazo que indique cada formulario",
        "updated": "25 de septiembre de 2026",
    }
