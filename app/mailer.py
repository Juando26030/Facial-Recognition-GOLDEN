"""Envío de correo (reunión 2026-09-21, ítem 6: informe final a la comercial).

SMTP se configura por variables de entorno (.env): SMTP_HOST, SMTP_PORT (587 por defecto),
SMTP_USER, SMTP_PASSWORD, SMTP_FROM (por defecto SMTP_USER), SMTP_TLS ("false" para desactivar
STARTTLS). Sin SMTP_HOST el correo NO se envía: se guarda como archivo .eml en `data/outbox/` para
poder revisarlo (así en desarrollo/QA local nunca sale un correo real por accidente).
"""
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Optional


def send_mail(to: str, subject: str, body: str, attachments: Optional[list] = None) -> dict:
    """`attachments`: lista de (nombre_archivo, bytes, mime "tipo/subtipo"). Devuelve
    {"sent": bool, "detail": str} — nunca lanza: quien llama decide qué mostrar."""
    msg = EmailMessage()
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "no-reply@golden.local"
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    for filename, content, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)

    if not host:
        os.makedirs(os.path.join("data", "outbox"), exist_ok=True)
        path = os.path.join("data", "outbox", f"{int(time.time())}_{to.replace('@', '_at_')}.eml")
        with open(path, "wb") as f:
            f.write(bytes(msg))
        return {"sent": False, "detail": f"SMTP no configurado — el correo quedó guardado en {path}"}

    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as server:
            if os.getenv("SMTP_TLS", "true").lower() != "false":
                server.starttls()
            if os.getenv("SMTP_USER"):
                server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            server.send_message(msg)
        return {"sent": True, "detail": f"Correo enviado a {to}"}
    except Exception as e:  # el informe ya quedó guardado; el correo se puede reintentar
        return {"sent": False, "detail": f"No se pudo enviar el correo: {e}"}
