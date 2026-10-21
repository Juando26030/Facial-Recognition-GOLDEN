"""Páginas legales públicas (sin login): Política de Privacidad, Términos y Condiciones y Política de Reembolsos. Ver app/legal.py y los borradores
en templates/legal_*.html (marcados PENDIENTE DE REVISIÓN LEGAL)."""
from fastapi import APIRouter, Request

router = APIRouter()


def _page(request: Request, template: str, title: str):
    from app.main import templates  # import tardío: main.py importa este módulo
    from app import legal
    name = template.replace("legal_", "").replace(".html", "")
    return templates.TemplateResponse(request=request, name=template, context={"page_title": title, "review": legal.review_status(name)})


@router.get("/privacidad")
def privacidad(request: Request):
    """La versión VIGENTE (POLICY_VERSION): la 1.1 ratificada si está activada y el archivo es exactamente el ratificado; si no, la 1.0."""
    from app import policy_v11
    if policy_v11.active_version() == "1.1":
        text = policy_v11.load_verified()
        if text is not None:
            from app.main import templates
            return templates.TemplateResponse(request=request, name="legal_privacidad_v11.html", context={"page_title": "Política de Privacidad", "ratified": policy_v11.legend(), "body": policy_v11.to_html(text)})
    return _page(request, "legal_privacidad.html", "Política de Privacidad")


@router.get("/privacidad/v1.0")
def privacidad_v10(request: Request):
    """La versión 1.0 (con constancia de revisión del 5 de octubre de 2026), histórica."""
    from app import legal
    from app.main import templates
    return templates.TemplateResponse(request=request, name="legal_privacidad.html", context={"page_title": "Política de Privacidad (versión 1.0, histórica)", "review": legal.review_status("privacidad"), "historic": True})


@router.get("/terminos")
def terminos(request: Request):
    return _page(request, "legal_terminos.html", "Términos y Condiciones")


@router.get("/reembolsos")
def reembolsos(request: Request, e: int = 0, f: str = ""):
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
