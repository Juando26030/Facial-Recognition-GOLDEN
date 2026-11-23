"""Manejador de la cola para el correo de «Pide tu cotización» (kind `quote_mail`). El correo es el único registro de la solicitud."""
import logging
import os

from app import jobs
from app.quote_core import MAIL_KIND

log = logging.getLogger("quote")


@jobs.handler(MAIL_KIND)
def run_quote_mail(payload: dict) -> None:
    """Idempotente: un reintento solo repite el envío si el anterior falló (el trabajo se marca terminado al enviar)."""
    from app.mailer import send_mail
    to = (os.getenv("QUOTE_TO_EMAIL") or "").strip()
    quote = payload.get("quote")
    if not to or not isinstance(quote, dict):
        log.warning("QUOTE_TO_EMAIL sin configurar" if not to else "solicitud de cotización sin contenido")
        return
    result = send_mail(to, quote["subject"], quote["text"], reply_to=quote.get("reply_to"))
    if not result.get("sent"):
        if "quedó guardado" in str(result.get("detail")):
            log.warning("cotización: el correo no está configurado; quedó guardado")
            return
        raise RuntimeError("no se pudo enviar la solicitud de cotización")
