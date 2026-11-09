"""STUB (agente A, Fase 6): autenticación de un servidor local ante la nube por token de nodo.

El agente B construye la versión real (token por nodo, revocable, guardado como huella) con la MISMA firma: `require_node(request) -> dict` con al menos {"name": str}.
Al unir las ramas, el archivo de B reemplaza a este. Cabecera: `X-Node-Token`. Aquí solo se compara con la variable NODE_TOKEN_STUB (para que las rutas funcionen y se prueben)."""
import hmac
import os

from fastapi import HTTPException, Request


def require_node(request: Request) -> dict:
    expected = os.getenv("NODE_TOKEN_STUB", "")
    given = request.headers.get("X-Node-Token", "")
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Token de nodo no válido")
    name = " ".join((request.headers.get("X-Node-Name") or "Servidor local").split())[:60] or "Servidor local"
    return {"name": name}
