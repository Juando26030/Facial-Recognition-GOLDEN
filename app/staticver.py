"""URLs de archivos estáticos con versión (`/static/js/x.js?v=<fecha del archivo>`).

Cloudflare y el navegador guardan `/static/*` hasta 4 h (`Cache-Control: max-age=14400`); sin versión en la URL, tras un deploy la gente sigue usando el
JS/CSS viejo. Se instala en cada `Jinja2Templates` del proyecto (hoy: `app/main.py` y `app/routers/auth.py`).

Devuelve SOLO la ruta (`/static/...`), nunca una URL absoluta: detrás de Firebase Hosting la app ve el host interno de Cloud Run y `http`,
así que una URL absoluta salía como `http://…run.app/static/…` y el navegador la bloqueaba en la página `https` (contenido mixto: la
página quedaba sin estilos). Con la ruta, el navegador la pide al mismo dominio y Firebase la sirve desde su CDN.
"""
import os

from jinja2 import pass_context

from app import legal


@pass_context
def _url_for(context, name, /, **path_params):
    url = context["request"].url_for(name, **path_params).path
    if name == "static":
        try:
            return f"{url}?v={int(os.path.getmtime(os.path.join('static', str(path_params.get('path', '')))))}"
        except OSError:
            pass
    return url


def install(templates) -> None:
    templates.env.globals["url_for"] = _url_for
    templates.env.globals["legal"] = legal.info      # datos legales del negocio para el pie de las páginas públicas
