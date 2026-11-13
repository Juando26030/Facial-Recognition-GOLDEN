"""Dibuja TODAS las plantillas crm_*.html con el `url_for` REAL de la app (app/staticver.py), sin base de datos.
Habría atrapado el error de staging: macros importadas sin «with context» no ven `request` (KeyError 'request') y la pantalla da 500."""
import glob
import json
import os
import sys
import types

import pytest

jinja2 = pytest.importorskip("jinja2")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Req:
    session = {"staff_role": "admin", "staff_name": "Admin Ficticio"}
    headers, cookies, query_params = {}, {}, {}

    def url_for(self, name, **kw):
        return types.SimpleNamespace(path="/static/" + str(kw.get("path", "")) if name == "static" else "/" + name)


def _env():
    try:
        from app import staticver
    except ModuleNotFoundError:                                  # sin SQLAlchemy (entorno mínimo): se sustituye solo `app.legal`
        import app
        fake = types.ModuleType("app.legal")
        fake.info = lambda *a, **k: {}
        sys.modules["app.legal"], app.legal = fake, fake
        from app import staticver
    holder = types.SimpleNamespace(env=jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(ROOT, "templates"))))
    staticver.install(holder)
    holder.env.globals.update(company_name="G", event_logo_url=lambda e: "", event_logo_attrs=lambda e: "", golden_logo_attrs=lambda *a: "", crm_nav_visible=lambda r: True,
                              local_server=False, public_base_url=lambda *a: "", print_settings_json=lambda *a: "{}")
    holder.env.filters.update(fromjson=json.loads, local_dt=lambda d: "")
    return holder.env


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(ROOT, "templates", "crm_*.html"))), ids=os.path.basename)
def test_crm_template_renders_with_the_real_url_for(path):
    html = _env().get_template(os.path.basename(path)).render(request=_Req(), staff_name="X", staff_role="admin", sidebar_active="crm", can_admin=True, account_id="", csrf_token="t")
    assert "gw-page-head__title" in html and "/static/img/icons.svg" in html
