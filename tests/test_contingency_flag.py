"""Modo contingencia del quiosco apagable (CONTINGENCY_ENABLED, docs/15 D2.5d): apagado por defecto (nada de GoldenContingency ni de service worker; el worker servido se desregistra y borra sus cachés)
y encendido como antes. Producción lo lleva apagado desde deploy/gcp/config.sh."""
import pathlib

import pytest

from tests.conftest import login


def _page(client, factory):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff("coordinador", "coord2"))
    login(client, "coord2")
    r = client.get(f"/kiosk/{ev.id}/registro")
    assert r.status_code == 200, r.text[:200]
    return r.text


def test_off_by_default_the_page_loads_no_contingency_client_and_registers_no_worker(client, factory, monkeypatch):
    monkeypatch.delenv("CONTINGENCY_ENABLED", raising=False)
    html = _page(client, factory)
    assert "js/contingency-off.js" in html and "js/contingency.js" not in html
    assert "&& false && 'serviceWorker' in navigator" in html


def test_on_the_page_keeps_the_contingency_client_and_registers_the_worker(client, factory, monkeypatch):
    monkeypatch.setenv("CONTINGENCY_ENABLED", "1")
    html = _page(client, factory)
    assert "js/contingency.js" in html and "contingency-off.js" not in html
    assert "&& true && 'serviceWorker' in navigator" in html


@pytest.mark.parametrize("value", ["0", "", "no", "false"])
def test_only_explicit_truthy_values_turn_it_on(monkeypatch, value):
    from app.main import contingency_enabled
    monkeypatch.setenv("CONTINGENCY_ENABLED", value)
    assert contingency_enabled() is False


def test_worker_endpoint_serves_the_self_removing_worker_when_off_and_the_real_one_when_on(client, monkeypatch):
    monkeypatch.setenv("CONTINGENCY_ENABLED", "0")
    r = client.get("/kiosk/sw.js")
    assert r.status_code == 200 and "unregister()" in r.text and "fetch" not in r.text.replace("intercepta", "") and r.headers["cache-control"].startswith("no-cache")
    monkeypatch.setenv("CONTINGENCY_ENABLED", "1")
    r = client.get("/kiosk/sw.js")
    assert r.status_code == 200 and "addEventListener('fetch'" in r.text and "__BUILD__" not in r.text


def test_deploy_config_turns_it_on_in_staging_only():
    """config.sh decide: producción SIEMPRE 0 (aunque la variable venga puesta); staging 1 salvo que se pida otra cosa; deploy.sh la escribe en el YAML de cada servicio."""
    src = pathlib.Path("deploy/gcp/config.sh").read_text(encoding="utf8")
    assert 'if [ "$GOLDEN_ENV" = production ]; then CONTINGENCY_ENABLED=0; else CONTINGENCY_ENABLED="${CONTINGENCY_ENABLED:-1}"; fi' in src
    assert 'echo "CONTINGENCY_ENABLED: \\"$CONTINGENCY_ENABLED\\""' in pathlib.Path("deploy/gcp/deploy.sh").read_text(encoding="utf8")
