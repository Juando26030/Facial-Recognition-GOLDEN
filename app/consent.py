"""Registro de consentimientos biométricos (`audit_consent_logs`, migración 0054): prueba de la autorización de cada persona, por evento.

Solo se inserta (ver el modelo): aquí no hay UPDATE ni DELETE y no debe haberlos. Vigencia de la aceptación = el ÚLTIMO registro de la persona en ese evento
(una revocación o un rechazo posterior la anula; una nueva aceptación la restablece). Nada de lo que se guarda va a los logs de la aplicación.
"""
import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import AuditConsentLog
from app.timeutil import utcnow

REASONS = ("consent", "rejection", "revocation")


def text_hash(text: str) -> str:
    """SHA-256 del texto EXACTO que vio la persona (tal como se mostró, con sus variables ya reemplazadas)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cedula_hash(cedula: str) -> str:
    """HMAC-SHA256 de la cédula normalizada con SECRET_KEY: permite encontrar a la persona aunque su fila de `users` ya no exista, sin guardar la cédula en claro aparte."""
    key = (os.getenv("SECRET_KEY") or "dev-only-insecure-key-do-not-use-in-production").encode()
    return hmac.new(key, b"consent-cedula:" + re.sub(r"[\s.]", "", str(cedula or "")).encode(), hashlib.sha256).hexdigest()


def record(db: Session, *, tenant_id: str, user_id: str, event_id: int, version: str, legal_text_hash: str, accepted: bool, adult: bool, reason: str,
           device: Optional[str] = None, entry_id: Optional[str] = None, at: Optional[datetime] = None) -> bool:
    """Inserta un registro. `entry_id` (UUID generado en el dispositivo) lo hace idempotente: repetirlo no duplica. Devuelve True si se insertó. No hace commit."""
    if reason not in REASONS:
        raise ValueError("reason inválido")
    when = at or utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    row = dict(id=entry_id or str(uuid.uuid4()), tenant_id=tenant_id, user_id=str(user_id), cedula_hash=cedula_hash(user_id),
               event_id=event_id, consent_timestamp_utc=when, consent_version=version, legal_text_hash=legal_text_hash, accepted_biometric=bool(accepted),
               confirmed_adult=bool(adult), ip_or_device_id=(device or None), reason=reason)
    res = db.execute(pg_insert(AuditConsentLog).values(**row).on_conflict_do_nothing(index_elements=["id"]))
    return res.rowcount == 1


def latest(db: Session, tenant_id: str, user_id: str, event_id: int) -> Optional[AuditConsentLog]:
    return db.execute(select(AuditConsentLog).where(AuditConsentLog.tenant_id == tenant_id, AuditConsentLog.user_id == str(user_id), AuditConsentLog.event_id == event_id)
                      .order_by(AuditConsentLog.consent_timestamp_utc.desc(), AuditConsentLog.id.desc()).limit(1)).scalar_one_or_none()


def has_acceptance(db: Session, tenant_id: str, user_id: str, event_id: int) -> bool:
    """¿Hay aceptación VIGENTE de la persona para este evento? (el último registro es un `consent` con `accepted_biometric` y `confirmed_adult`)."""
    row = latest(db, tenant_id, user_id, event_id)
    return bool(row and row.reason == "consent" and row.accepted_biometric and row.confirmed_adult)
