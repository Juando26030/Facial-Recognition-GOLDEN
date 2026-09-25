"""Envío de correo (reunión 2026-09-21, ítem 6: informe final a la comercial; ítem 17: escarapela digital).

Tres caminos, en este orden de preferencia:
1. **Microsoft Graph API (OAuth2 client credentials)** — si están `AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/
   `AZURE_CLIENT_SECRET`/`GRAPH_SENDER` en `.env`. El camino recomendado para un buzón de Microsoft 365
   corporativo: nada de contraseñas ni SMTP AUTH (que Microsoft está retirando), solo un token de app.
   Requiere una App Registration en Entra ID con el permiso de aplicación `Mail.Send` (consentida por un
   admin) — ver la guía en `.env.example`.
2. **SMTP** (`SMTP_HOST`/...) — sigue disponible para cualquier otro proveedor (o un M365 con SMTP AUTH
   ya habilitado a mano), sin cambios respecto a antes.
3. Sin ninguno de los dos configurado, el correo NO se envía: se guarda como archivo `.eml` en
   `data/outbox/` (así en desarrollo/QA local nunca sale un correo real por accidente).
"""
import base64
import json
import os
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Optional

_graph_token_cache = {"token": None, "exp": 0.0}


def _graph_token() -> str:
    """Token de aplicación (client credentials, sin usuario de por medio) — se cachea en memoria hasta
    un minuto antes de que expire para no pedir uno nuevo en cada correo."""
    now = time.time()
    if _graph_token_cache["token"] and _graph_token_cache["exp"] > now + 60:
        return _graph_token_cache["token"]
    tenant = os.environ["AZURE_TENANT_ID"]
    data = urllib.parse.urlencode({
        "client_id": os.environ["AZURE_CLIENT_ID"],
        "client_secret": os.environ["AZURE_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.load(resp)
    _graph_token_cache["token"] = payload["access_token"]
    _graph_token_cache["exp"] = now + payload.get("expires_in", 3600)
    return _graph_token_cache["token"]


def _send_via_graph(to: str, subject: str, body: str, attachments: list, html: Optional[str] = None) -> dict:
    sender = os.environ["GRAPH_SENDER"]
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html} if html else {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    if attachments:
        message["attachments"] = [
            {"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": mime,
             "contentBytes": base64.b64encode(content).decode()}
            for name, content, mime in attachments
        ]
    body_json = json.dumps({"message": message, "saveToSentItems": "false"}).encode()
    try:
        # El token también se pide acá adentro: si login.microsoftonline.com falla (credenciales
        # malas, tenant caído), debe devolver el mismo {"sent": False, ...} de siempre, nunca lanzar.
        req = urllib.request.Request(
            f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail", data=body_json,
            headers={"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return {"sent": True, "detail": f"Correo enviado a {to} (Microsoft Graph)"}
    except urllib.error.HTTPError as e:
        return {"sent": False, "detail": f"No se pudo enviar el correo (Graph): {e.read().decode(errors='replace')[:300]}"}
    except Exception as e:
        return {"sent": False, "detail": f"No se pudo enviar el correo (Graph): {e}"}


def _outbox_fallback(msg: EmailMessage, to: str, reason: str) -> dict:
    os.makedirs(os.path.join("data", "outbox"), exist_ok=True)
    path = os.path.join("data", "outbox", f"{int(time.time())}_{to.replace('@', '_at_')}.eml")
    with open(path, "wb") as f:
        f.write(bytes(msg))
    return {"sent": False, "detail": f"{reason} — el correo quedó guardado en {path}"}


def send_mail(to: str, subject: str, body: str, attachments: Optional[list] = None, html: Optional[str] = None) -> dict:
    """`attachments`: lista de (nombre_archivo, bytes, mime "tipo/subtipo"). Devuelve
    {"sent": bool, "detail": str} — nunca lanza: quien llama decide qué mostrar. `html`: versión con formato (el `body` queda como texto alterno)."""
    attachments = attachments or []

    if all(os.getenv(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "GRAPH_SENDER")):
        return _send_via_graph(to, subject, body, attachments, html)

    msg = EmailMessage()
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "no-reply@golden.local"
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for filename, content, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)

    if not host:
        return _outbox_fallback(msg, to, "Ni Microsoft Graph ni SMTP están configurados")

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
