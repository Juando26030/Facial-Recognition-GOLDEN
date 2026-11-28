"""Páginas legales públicas (sin login): Política de Privacidad, Términos y Condiciones y Política de Reembolsos. Ver app/legal.py y los borradores
en templates/legal_*.html (Privacidad, Términos y Reembolsos: aprobados por la auditora el 5-6 de octubre de 2026)."""
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

router = APIRouter()


# Términos y Condiciones y Política de Reembolsos: aprobados por la auditora el 6 de octubre de 2026 junto con la Política de Privacidad (dicho por Juan David el 18-nov-2026;
# la constancia escrita se archiva en docs/legal/). Por eso ya no salen como «borrador pendiente de revisión legal».
APPROVED_WITH_PRIVACY = "Texto aprobado por la auditora el 6 de octubre de 2026, junto con la Política de Privacidad."

# SEO (22-nov-2026, docs/revision_2026-11-22/08 P1-P3): la plataforma no compite con el sitio corporativo. Los buscadores solo entran a las tres páginas legales;
# el resto (ingreso, formularios, enlaces personales) queda fuera. El mapa del sitio es el del sitio corporativo. Sin base ni sesión; se guarda 1 hora.
INDEXABLE_PATHS = ("/privacidad", "/terminos", "/reembolsos")
CORPORATE_SITEMAP = "https://golden-eventos.com/sitemap.xml"
ROBOTS_TXT = "User-agent: *\nDisallow: /\n" + "".join(f"Allow: {p}$\n" for p in INDEXABLE_PATHS) + f"\nSitemap: {CORPORATE_SITEMAP}\n"
# Descripción breve de cada página para los buscadores (no es texto legal: resume de qué trata la página).
DESCRIPTIONS = {
    "privacidad": "Cómo Golden Eventos y Logística S.A.S. trata los datos personales en Orum: qué datos se recogen, para qué, por cuánto tiempo y cómo ejercer sus derechos (Ley 1581 de 2012).",
    "terminos": "Términos y condiciones de uso de Orum, la plataforma de inscripciones y control de acceso a eventos de Golden Eventos y Logística S.A.S.",
    "reembolsos": "Política de reembolsos y devoluciones de los pagos de inscripciones a eventos hechos en Orum, de Golden Eventos y Logística S.A.S.",
}


@router.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return PlainTextResponse(ROBOTS_TXT, headers={"Cache-Control": "public, max-age=3600"})


def _page(request: Request, template: str, title: str):
    from app.main import templates  # import tardío: main.py importa este módulo
    from app import legal
    name = template.replace("legal_", "").replace(".html", "")
    ratified = APPROVED_WITH_PRIVACY if name in ("terminos", "reembolsos") else None
    return templates.TemplateResponse(request=request, name=template, context={"page_title": title, "page_description": DESCRIPTIONS[name], "review": legal.review_status(name), "ratified": ratified})


@router.get("/privacidad")
def privacidad(request: Request):
    """La versión VIGENTE (POLICY_VERSION): la 1.1 ratificada si está activada y el archivo es exactamente el ratificado; si no, la 1.0."""
    from app import policy_v11
    if policy_v11.active_version() == "1.1":
        text = policy_v11.load_verified()
        if text is not None:
            from app.main import templates
            return templates.TemplateResponse(request=request, name="legal_privacidad_v11.html", context={"page_title": "Política de Privacidad", "page_description": DESCRIPTIONS["privacidad"], "ratified": policy_v11.legend(), "body": policy_v11.to_html(text)})
    return _page(request, "legal_privacidad.html", "Política de Privacidad")


@router.get("/privacidad/v1.0")
def privacidad_v10(request: Request):
    """La versión 1.0 (con constancia de revisión del 5 de octubre de 2026), histórica."""
    from app import legal
    from app.main import templates
    return templates.TemplateResponse(request=request, name="legal_privacidad.html", context={"page_title": "Política de Privacidad (versión 1.0, histórica)", "page_description": DESCRIPTIONS["privacidad"], "canonical_path": "/privacidad", "review": legal.review_status("privacidad"), "historic": True})


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
    return templates.TemplateResponse(request=request, name="legal_reembolsos.html", context={"page_title": "Política de Reembolsos", "page_description": DESCRIPTIONS["reembolsos"], "form_refund": extra, "ratified": APPROVED_WITH_PRIVACY})
