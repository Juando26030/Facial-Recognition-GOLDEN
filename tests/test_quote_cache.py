"""`POST /f/<evento>/<slug>/quote`: el caso común (sin código de descuento ni clave de pruebas) no toca la base ni usa un hilo; con código o con clave de pruebas sí consulta; el cambio de
diseño se ve al vencer la caché; el límite por IP y el 404 siguen igual."""
import json

import pytest
from sqlalchemy import event

from app import formsvc
from app.database import engine
from app.routers import form_payments, forms_public
from tests.test_form_payments import _event, _pay, _url, _with_payment
from tests.test_forms import _basic_fields, _design, _put


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch):
    monkeypatch.setattr(formsvc.public_cache, "ttl", 60)                  # conftest apaga la caché del estado público (FORM_PUBLIC_CACHE_SECONDS=0): aquí se enciende
    formsvc.public_cache.clear()
    yield
    formsvc.public_cache.clear()


def _sql(fn):
    sent = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        sent.append(" ".join(statement.split())[:80])

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        return fn(), sent
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def _quote(client, ev, form, **body):
    return client.post(f"{_url(ev, form)}/quote", json={"values": {}, **body})


def test_common_quotes_touch_neither_the_database_nor_the_thread_pool_after_the_first(client, factory, monkeypatch):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    first = _quote(client, ev, form)
    assert first.status_code == 200 and first.json()["has_payment"] is True and first.json()["amount"] == 150000

    def boom(*a, **k):
        raise AssertionError("un acierto de caché no debe usar el pool de hilos")

    monkeypatch.setattr(form_payments.timing, "run", boom)
    monkeypatch.setattr(forms_public, "SessionLocal", boom)
    monkeypatch.setattr(form_payments, "SessionLocal", boom)
    results, sql = _sql(lambda: [_quote(client, ev, form).json() for _ in range(25)])
    assert sql == [] and all(r == first.json() for r in results)           # 25 cotizaciones, ninguna consulta, mismo resultado


def test_a_code_goes_to_the_database_and_still_reports_its_status(client, factory):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    _quote(client, ev, form)                                                # calienta el contexto
    r, sql = _sql(lambda: _quote(client, ev, form, code="NOEXISTE"))
    assert r.status_code == 200 and r.json()["code"]["status"] == "invalid" and sql                  # con código: consulta la base
    r2, sql2 = _sql(lambda: _quote(client, ev, form))
    assert "code" not in r2.json() and sql2 == []                                                   # y sin código otra vez ninguna


def test_a_form_without_payment_and_a_missing_form_behave_as_before(client, factory):
    ev = _event(client, factory)
    from tests.test_forms import _create, _open
    plain = _create(client, ev)
    _open(client, ev, plain)
    assert _quote(client, ev, plain).json() == {"has_payment": False}
    assert client.post(f"/f/{ev.id}/no-existe/quote", json={"values": {}}).status_code == 404


def test_the_test_key_path_never_uses_the_cache(client, factory, db):
    ev = _event(client, factory)
    form = _with_payment(client, ev, status="pruebas")
    assert _quote(client, ev, form).status_code == 404                      # en pruebas y sin clave: como si no existiera (y el 404 no se guarda)
    from app.models import WebForm
    key = db.get(WebForm, form["id"]).test_key
    first, sql1 = _sql(lambda: _quote(client, ev, form, k=key))
    second, sql2 = _sql(lambda: _quote(client, ev, form, k=key))
    assert first.status_code == 200 and second.status_code == 200 and sql1 and sql2        # con clave de pruebas siempre consulta
    assert _quote(client, ev, form).status_code == 404                      # la clave no dejó nada en la caché compartida


def test_a_design_change_is_seen_at_once_in_this_process_and_when_the_cache_expires_in_the_others(client, factory):
    """Editar el formulario vacía la caché pública de ESE proceso (`invalidate_public_cache`): el `quote` hereda la invalidación. En los demás procesos el diseño nuevo se ve al vencer la
    caché (unos segundos): es solo una vista previa, el precio que se cobra lo recalcula el envío con el diseño vigente."""
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    assert _quote(client, ev, form).json()["amount"] == 150000
    from tests.conftest import login
    from tests.test_forms import _status
    factory.staff("admin", "root")
    login(client, "root")
    assert _put(client, ev, form, design=_design(_basic_fields() + [_pay(amount=90000)])).status_code == 200
    assert _status(client, ev, form, manual_status="activo").status_code == 200
    client.post("/logout")
    assert _quote(client, ev, form).json()["amount"] == 90000               # este proceso: al instante
    # otro proceso: conserva el contexto viejo hasta que venza; se simula guardando el diseño viejo en la caché compartida
    formsvc.public_cache.set(("quote", ev.id, form["slug"]), {"id": form["id"], "design": _design(_basic_fields() + [_pay(amount=150000)])})
    assert _quote(client, ev, form).json()["amount"] == 150000
    formsvc.public_cache.clear()                                            # (vence)
    assert _quote(client, ev, form).json()["amount"] == 90000


def test_the_ip_limit_still_applies_to_cached_quotes(client, factory, monkeypatch):
    ev = _event(client, factory)
    form = _with_payment(client, ev)
    monkeypatch.setattr(forms_public, "LIMIT_FACTOR", 0.002)                # max(1, int(600 × 0,002)) = 1 por ventana
    forms_public._limiter.__init__()
    assert _quote(client, ev, form).status_code == 200
    assert _quote(client, ev, form).status_code == 429
