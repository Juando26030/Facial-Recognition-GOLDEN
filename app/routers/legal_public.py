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
async def reembolsos(request: Request, e: int = 0, f: str = ""):
    """Con `?e=<evento>&f=<formulario>` (el enlace del cuadro de pago) muestra además las condiciones de reembolso de ESE formulario."""
    from app.database import SessionLocal
    from app.models import WebForm
    from app import formsvc
    extra = None
    if e and f:
        db = SessionLocal()
        try:
            form = db.query(WebForm).filter_by(event_id=e, slug=f).first()
            if form and formsvc.status_of(form) != "finalizado":
                r = formsvc.get_settings(form)["refunds"]
                extra = {"name": form.name, "days": r["days"], "note": r["note"]}
        finally:
            db.close()
    from app.main import templates
    return templates.TemplateResponse(request=request, name="legal_reembolsos.html", context={"page_title": "Política de Reembolsos", "form_refund": extra})
