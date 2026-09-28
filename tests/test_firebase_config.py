"""Firebase Hosting manda cada ruta al MISMO servicio que la app acepta (app/appmode.py); si no, una ruta daría 404 detrás del dominio."""
import json
import re

import pytest

from app import appmode
from deploy.firebase.make_config import build


def _glob(pattern: str) -> re.Pattern:
    """Globs de Firebase Hosting: «**» cualquier cosa, «*» un segmento."""
    rx = re.escape(pattern).replace(r"\*\*", "§").replace(r"\*", "[^/]+").replace("§", ".*")
    return re.compile(f"^{rx}$")


@pytest.fixture(scope="module")
def config(tmp_path_factory):
    out = build("staging", "proyecto", "us-east1", "golden-staging-1", str(tmp_path_factory.mktemp("fb")))
    return json.load(open(f"{out}/firebase.json", encoding="utf8"))["hosting"]


def _service_for(config, path):
    for rule in config["rewrites"]:
        if _glob(rule["source"]).match(path):
            return rule["run"]["serviceId"]


@pytest.mark.parametrize("path", [
    "/f/12/feria", "/f/12/feria/submit", "/b/abc", "/c/tok/pdf", "/r/tok/state", "/webhooks/wompi", "/privacidad", "/terminos",
    "/reembolsos", "/api/email-assets/acme/x.png", "/api/recognize", "/api/register", "/api/bulk_register", "/api/bulk_jobs/9f",
    "/api/events/3/areas/7/movement-face", "/api/users", "/kiosk/3/registro", "/login", "/", "/healthz", "/readyz", "/api/ops/status",
])
def test_each_path_goes_to_the_service_that_serves_it(config, path):
    service = _service_for(config, path)
    mode = service.removeprefix("golden-").removesuffix("-staging")
    assert appmode.route_allowed(re.sub(r"/(3|7|9f)(?=/|$)", lambda m: {"3": "/{event_id}", "7": "/{area_id}", "9f": "/{job_id}"}[m.group(1)], path)
                                 if mode == "biometria" else path, mode=mode), (path, service)


def test_static_files_come_from_the_cdn(config):
    assert config["public"] == "public" and config["headers"][0]["source"] == "/static/**"
