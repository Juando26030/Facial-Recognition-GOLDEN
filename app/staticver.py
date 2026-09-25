"""URLs de archivos estáticos con versión (`/static/js/x.js?v=<fecha del archivo>`).

Cloudflare y el navegador guardan `/static/*` hasta 4 h (`Cache-Control: max-age=14400`); sin versión en la URL, tras un deploy la gente sigue usando el
JS/CSS viejo. Se instala en cada `Jinja2Templates` del proyecto (hoy: `app/main.py` y `app/routers/auth.py`).
"""
import os

from jinja2 import pass_context


@pass_context
def _url_for(context, name, /, **path_params):
    url = context["request"].url_for(name, **path_params)
    if name == "static":
        try:
            return f"{url}?v={int(os.path.getmtime(os.path.join('static', str(path_params.get('path', '')))))}"
        except OSError:
            pass
    return url


def install(templates) -> None:
    templates.env.globals["url_for"] = _url_for
