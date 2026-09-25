"""Páginas legales públicas (sin login): Política de Privacidad, Términos y Condiciones y Política de Reembolsos. Ver app/legal.py y los borradores
en templates/legal_*.html (marcados PENDIENTE DE REVISIÓN LEGAL)."""
from fastapi import APIRouter, Request

router = APIRouter()


def _page(request: Request, template: str, title: str):
    from app.main import templates  # import tardío: main.py importa este módulo
    return templates.TemplateResponse(request=request, name=template, context={"page_title": title})


@router.get("/privacidad")
async def privacidad(request: Request):
    return _page(request, "legal_privacidad.html", "Política de Privacidad")


@router.get("/terminos")
async def terminos(request: Request):
    return _page(request, "legal_terminos.html", "Términos y Condiciones")


@router.get("/reembolsos")
async def reembolsos(request: Request):
    return _page(request, "legal_reembolsos.html", "Política de Reembolsos")
