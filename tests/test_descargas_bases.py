"""Fase 4: descargas de la base de digitadores y la base de clientes. Matriz por rol, aislamiento por cliente, fórmulas, auditoría y tope por hora."""
import csv
import io

import pytest
from openpyxl import load_workbook

from app import download_perms
from app.models import AuditAction, RateLimitEvent
from tests.conftest import login

DIG = "/api/staff/export?kind=digitadores"
CLI = "/api/tenants/export"


def _wb(res):
    return load_workbook(io.BytesIO(res.content))


def _as(client, factory, role, **kw):
    s = factory.staff(role, **kw)
    assert login(client, s.username).status_code in (200, 302, 303)
    return s


@pytest.mark.parametrize("role,dig,cli", [
    ("digitador", 403, 403), ("cliente", 403, 403), ("coordinador", 200, 403), ("comercial", 200, 200), ("admin", 200, 200), ("super_admin", 200, 200),
])
def test_matriz_rol_por_base(client, factory, role, dig, cli):
    factory.tenant("acme")
    _as(client, factory, role)
    assert client.get(DIG).status_code == dig
    assert client.get(CLI).status_code == cli


def test_doble_rol_coordinador_comercial_descarga_ambas(client, factory):
    factory.tenant("acme")
    _as(client, factory, "coordinador", secondary_role="comercial")
    assert client.get(DIG).status_code == 200
    assert client.get(CLI).status_code == 200


def test_sin_sesion_no_descarga(client):
    assert client.get(DIG).status_code in (401, 403)
    assert client.get(CLI).status_code in (401, 403)


def test_permisos_en_un_solo_modulo_y_extensibles(monkeypatch):
    class S:
        role, secondary_role = "contabilidad", None
    assert not download_perms.can_download(S, "digitadores")
    monkeypatch.setitem(download_perms.DOWNLOAD_ROLES, "digitadores", download_perms.DOWNLOAD_ROLES["digitadores"] | {"contabilidad"})
    assert download_perms.can_download(S, "digitadores")
    assert not download_perms.can_download(S, "clientes")


def test_base_digitadores_contenido_sin_secretos(client, factory):
    ev = factory.event()
    d = factory.staff("digitador", username="1012345678", phone="+573001112233")
    factory.authorize(ev, d)
    _as(client, factory, "admin")
    res = client.get(DIG)
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["content-disposition"].startswith('attachment; filename="base_digitadores_') and res.headers["content-disposition"].endswith('.xlsx"')
    rows = list(_wb(res).active.iter_rows(values_only=True))
    assert rows[0][0] == "Cédula" and any(r[0] == "1012345678" and ev.event_code in r[4] for r in rows[1:])
    blob = res.content
    assert d.password_hash.encode() not in blob
    flat = " ".join(str(c) for r in rows for c in r).lower()
    assert "password" not in flat and "hash" not in flat
    assert not any(str(r[5]) == "" for r in rows[1:])


def test_solo_digitadores_no_otros_roles(client, factory):
    factory.tenant("acme")
    c = factory.staff("coordinador", username="coordx")
    _as(client, factory, "admin")
    rows = list(_wb(client.get(DIG)).active.iter_rows(values_only=True))[1:]
    assert c.username not in [r[0] for r in rows]


def test_aislamiento_por_cliente_digitadores(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    a, b = factory.event(tenant_id="acme"), factory.event(tenant_id="beta")
    factory.authorize(a, factory.staff("digitador", username="d-acme", tenant_id="acme"))
    factory.authorize(b, factory.staff("digitador", username="d-beta", tenant_id="beta"))
    _as(client, factory, "coordinador", tenant_id="acme")
    ids = [r[0] for r in list(_wb(client.get(DIG)).active.iter_rows(values_only=True))[1:]]
    assert ids == ["d-acme"]


def test_alcance_por_evento_coordinador(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_EVENT_SCOPE", "1")
    coord = factory.staff("coordinador", username="coord-uno")
    mine, other = factory.event(coordinator=coord), factory.event()
    factory.authorize(mine, factory.staff("digitador", username="d-mio"))
    factory.authorize(other, factory.staff("digitador", username="d-ajeno"))
    login(client, coord.username)
    rows = list(_wb(client.get(DIG)).active.iter_rows(values_only=True))[1:]
    assert [r[0] for r in rows] == ["d-mio"]
    assert other.event_code not in str(rows)


def test_aislamiento_por_cliente_clientes(client, factory, monkeypatch):
    monkeypatch.setenv("ENFORCE_STAFF_TENANT", "1")
    factory.tenant("acme")
    factory.tenant("beta")
    _as(client, factory, "comercial", tenant_id="acme")
    codes = [r[0] for r in list(_wb(client.get(CLI)).worksheets[0].iter_rows(values_only=True))[1:]]
    assert codes == ["Cacme"]
    assert client.get(CLI + "?tenant_id=beta").status_code == 404


def test_base_clientes_hojas(client, factory):
    t = factory.tenant("acme")
    t.contact_name, t.contact_phone, t.contact_email = "Luis", "+573005550000", "luis@acme.test"
    cl = factory.staff("cliente", username="cli1", tenant_id="acme")
    _as(client, factory, "admin")
    wb = _wb(client.get(CLI))
    assert wb.sheetnames == ["Clientes", "Cuentas de cliente"]
    assert any(cl.full_name == r[1] for r in wb["Cuentas de cliente"].iter_rows(values_only=True))


def test_inyeccion_de_formulas_xlsx_y_csv(client, factory):
    ev = factory.event()
    d = factory.staff("digitador", username="999111", full_name='=HYPERLINK("http://x","a")')
    factory.authorize(ev, d)
    t = factory.tenant("acme")
    t.contact_name = "@SUM(1+1)"
    t.contact_email = "-2+3@x.test"
    _as(client, factory, "admin")
    rows = list(_wb(client.get(DIG)).active.iter_rows(values_only=True))
    assert any(r[1].startswith("'=HYPERLINK") for r in rows[1:])
    text = client.get(DIG + "&format=csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\n=" not in text and ",=" not in text
    text = client.get(CLI + "?format=csv").content.decode("utf-8-sig")
    got = list(csv.reader(io.StringIO(text)))
    assert any(r[2] == "'@SUM(1+1)" and r[4] == "'-2+3@x.test" for r in got[1:])
    assert client.get(CLI + "?format=csv").content.startswith(b"\xef\xbb\xbf")


def test_formato_invalido(client, factory):
    _as(client, factory, "admin")
    assert client.get(DIG + "&format=exe").status_code == 400
    assert client.get("/api/staff/export?kind=otra").status_code == 400


def test_auditoria_sin_datos_personales(client, factory, db):
    ev = factory.event()
    factory.authorize(ev, factory.staff("digitador", username="1077777777"))
    me = _as(client, factory, "admin")
    assert client.get(DIG).status_code == 200
    row = db.query(AuditAction).filter_by(action="export", entity="base_digitadores").one()
    assert row.actor_id == me.id and "1 filas" in row.detail
    assert "1077777777" not in f"{row.entity_name}{row.detail}{row.entity_id}"


def test_tope_por_hora(client, factory, db):
    factory.tenant("acme")
    me = _as(client, factory, "admin")
    for _ in range(download_perms.RATE_MAX):
        assert client.get(CLI).status_code == 200
    assert client.get(CLI).status_code == 429
    assert client.get(DIG).status_code == 429          # el tope es por usuario, no por base
    assert db.query(RateLimitEvent).filter_by(kind=download_perms.RATE_KIND, key=str(me.id)).count() == download_perms.RATE_MAX


def test_denegado_no_consume_cupo_ni_audita(client, factory, db):
    _as(client, factory, "coordinador")
    assert client.get(CLI).status_code == 403
    assert db.query(RateLimitEvent).filter_by(kind=download_perms.RATE_KIND).count() == 0
    assert db.query(AuditAction).filter_by(action="export").count() == 0
