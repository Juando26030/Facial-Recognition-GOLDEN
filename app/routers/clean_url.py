"""URL limpia de las inscripciones públicas: `GET /inscripciones/<evento>` (formulario principal) y `GET /inscripciones/<evento>/<formulario>` (docs/15 D2.5k, docs/20), en el MISMO host de la app.

Solo sirven la PÁGINA: el cascarón es el mismo de `/f/{id}/{slug}` y habla con `/f/{id}/{slug}/state|submit|…` en el mismo host (el prefijo `/inscripciones/` está en appmode.PUBLIC_PREFIXES: Firebase lo manda al servicio `publico`
y `/static` sale de la CDN, como todo lo público). Se registran AL FINAL de la aplicación y solo en `all` y `publico` (app/main.py), así que nunca tapan una ruta existente; un nombre reservado o desconocido da 404.
Un nombre de enlace viejo (slug_history) responde 301 al nuevo. `async` a propósito, como `page` del formulario: la resolución se sirve de la caché pública sin hilo ni base."""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import formsvc, public_slug
from app.database import SessionLocal
from app.routers import forms_public

router = APIRouter(prefix="/inscripciones")
_FORM_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")          # la forma de formlib.slugify (+ «-2», «-3»…): lo demás no existe


def bad_form_slug(form_slug: Optional[str]) -> bool:
    """F5-9 B: un nombre de formulario imposible da 404 SIN tocar la base ni llenar la caché pública (que comparten todos los formularios: llenarla de basura la vaciaría)."""
    return form_slug is not None and (len(form_slug) > 80 or not _FORM_SLUG.match(form_slug))


def _resolve(slug: str, form_slug: Optional[str]) -> dict:
    db = SessionLocal()
    try:
        return public_slug.resolve(db, slug, form_slug)
    finally:
        db.close()


async def _serve(request: Request, slug: str, form_slug: Optional[str], k: Optional[str]):
    s = slug.lower()
    form_slug = form_slug.lower() if form_slug is not None else None
    if public_slug.validate(s) or bad_form_slug(form_slug):                                       # reservados y nombres imposibles: 404 sin tocar la base
        raise HTTPException(status_code=404, detail="No encontrado")
    request.scope["public_form"] = True                               # cabeceras de formulario incrustable (app/main.py security_headers)
    key = ("slug", s, form_slug)
    found = await forms_public._cached_async(formsvc.public_cache, key, lambda: _resolve(s, form_slug))
    if "redirect" in found:
        tail = f"/{form_slug}" if form_slug else ""
        qs = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/inscripciones/{found['redirect']}{tail}{qs}", status_code=301)
    if not found:
        return HTMLResponse("<h3 style='font-family:sans-serif;text-align:center;margin-top:20vh'>Este formulario no está disponible</h3>", status_code=404)
    return await forms_public.render_shell(request, found["event_id"], found["form_slug"], k)


@router.get("/{evento}", response_class=HTMLResponse, include_in_schema=False)
async def event_page(evento: str, request: Request, k: Optional[str] = None):
    return await _serve(request, evento, None, k)


@router.get("/{evento}/{formulario}", response_class=HTMLResponse, include_in_schema=False)
async def form_page(evento: str, formulario: str, request: Request, k: Optional[str] = None):
    return await _serve(request, evento, formulario, k)
