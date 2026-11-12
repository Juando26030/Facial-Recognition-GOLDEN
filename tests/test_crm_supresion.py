"""CRM C1b-1: SUPRESIÓN (Ley 1581) de extremo a extremo. Suprimir un contacto borra su rastro en TODOS los sitios: su fila, sus notas, su historial, el historial de la cuenta que traiga sus valores,
los campos de la cuenta que hoy los tengan y la copia en `tenants`. Lo que no se puede decidir (texto libre) se avisa en `review`. La auditoría guarda solo ids, motivo y conteos. Necesitan PostgreSQL."""
import copy
import json

from app import account_sync, models as m
from tests.crm_helpers import crm_on, new_account, new_contact, staff_client  # noqa: F401

EMAIL, MOBILE = "ana.perez@empresa.com", "3001234567"
PERSONAL = ("ana", "perez", "pérez", EMAIL, MOBILE)


def _scenario(client, factory):
    """Cliente con dos contactos; Ana (principal) dejó sus datos también en campos de la cuenta, en el historial de la cuenta, en notas y en texto libre."""
    staff_client(client, factory, "admin", "adm_supr")
    a = new_account(client, "Cliente Uno", billing_city="Bogotá")
    tid = client.post(f"/api/crm/accounts/{a['id']}/make-client").json()["tenant_id"]
    ana = new_contact(client, a["id"], "Ana", "Pérez", email=EMAIL, mobile=MOBILE, phone="6015551234")
    beto = new_contact(client, a["id"], "Beto", "Gómez", email="beto@empresa.com", mobile="3109998888")
    client.put(f"/api/crm/contacts/{ana['id']}", json={"job_title": "Gerente", "updated_at": ana["updated_at"]})          # historial propio de Ana
    for fields in ({"email": EMAIL}, {"billing_contact_name": "Ana Pérez", "billing_contact_phone": "+57 300 123 4567"}, {"billing_city": "Medellín", "description": "Hablar con Ana Pérez cada lunes"}):
        cur = client.get(f"/api/crm/accounts/{a['id']}").json()
        assert client.put(f"/api/crm/accounts/{a['id']}", json={**fields, "updated_at": cur["updated_at"]}).status_code == 200
    client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "Pidió cotización", "contact_id": ana["id"]})
    client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "Reunión con Ana Pérez y Beto"})
    client.post(f"/api/crm/accounts/{a['id']}/notes", json={"body": "Nota sin nombres"})
    return a, tid, ana, beto


def test_erase_contact_removes_every_trace_and_reports_only_counts(client, factory, crm_on, db):
    a, tid, ana, beto = _scenario(client, factory)
    t = db.get(m.Tenant, tid)
    assert (t.contact_name, t.contact_email, t.contact_phone) == ("Ana Pérez", EMAIL, MOBILE)          # punto de partida: la copia existe
    url = f"/api/crm/contacts/{ana['id']}/erase"
    assert client.post(url, json={"reason": "", "confirm_name": "Ana Pérez"}).status_code == 400          # sin motivo
    assert client.post(url, json={"reason": "solicitud 123", "confirm_name": "Otra Persona"}).status_code == 400          # nombre que no coincide
    assert db.get(m.CrmContact, ana["id"]) is not None

    r = client.post(url, json={"reason": "solicitud 123", "confirm_name": "  ana pérez "})
    assert r.status_code == 200
    counts = r.json()["counts"]
    assert counts["contacts"] == 1 and counts["notes"] == 1 and counts["changes"] >= 1 and counts["tenant_fields"] == 3
    assert counts["account_fields"] == 3 and counts["account_history"] >= 3                                 # correo, contacto de facturación y su teléfono
    assert counts["review"] == {"description": True, "general_notes": 1}                                     # texto libre: se avisa, no se toca
    assert not any(p in json.dumps(r.json(), ensure_ascii=False).lower() for p in PERSONAL)               # la respuesta no trae datos personales

    db.expire_all()
    assert db.get(m.CrmContact, ana["id"]) is None and db.get(m.CrmContact, beto["id"]) is not None          # Beto sigue
    assert [n.body for n in db.query(m.CrmNote).filter_by(account_id=a["id"]).order_by(m.CrmNote.id)] == ["Reunión con Ana Pérez y Beto", "Nota sin nombres"]
    log = db.query(m.CrmChangeLog).all()
    assert log, "el historial de lo demás debe quedar"
    for row in log:
        if (row.entity, row.field_key) == ("account", "description"):
            continue          # TEXTO LIBRE: no se borra por valor (no se puede asegurar que sea suyo); se AVISA en `review` para que una persona lo revise
        assert not any(p in f"{row.old_value} {row.new_value}".lower() for p in PERSONAL), (row.field_key, row.entity)          # ningún otro valor suyo en NINGÚN historial
    assert counts["review"] == {"description": True, "general_notes": 1}          # y el aviso trae los conteos que la pantalla mostrará
    assert any(r_.field_key == "billing_city" and r_.new_value == "Medellín" for r_ in log)                   # lo que no era suyo se conserva
    acc = db.get(m.CrmAccount, a["id"])
    assert acc.email is None and acc.billing_contact_name is None and acc.billing_contact_phone is None and "Ana Pérez" in acc.description
    t = db.get(m.Tenant, tid)
    assert (t.contact_name, t.contact_email, t.contact_phone) == (None, None, None)                           # y la copia en el cliente

    audit = db.query(m.AuditAction).filter_by(action="erase", entity="crm_contact").one()
    blob = f"{audit.entity_name} {audit.detail}".lower()
    assert "solicitud 123" in blob and "contacts=1" in blob and not any(p in blob for p in PERSONAL)          # solo motivo y conteos


def test_only_the_matching_mirror_fields_are_cleared(client, factory, crm_on, db):
    a, tid, ana, beto = _scenario(client, factory)
    t = db.get(m.Tenant, tid)
    t.contact_email = "otro.correo@empresa.com"          # alguien lo escribió a mano distinto: no es de Ana
    db.commit()
    counts = client.post(f"/api/crm/contacts/{ana['id']}/erase", json={"reason": "x", "confirm_name": "Ana Pérez"}).json()["counts"]
    db.expire_all()
    t = db.get(m.Tenant, tid)
    assert counts["tenant_fields"] == 2 and t.contact_name is None and t.contact_phone is None and t.contact_email == "otro.correo@empresa.com"


def test_the_cleared_mirror_reaches_the_local_server_through_account_sync(client, factory, crm_on, db):
    a, tid, ana, beto = _scenario(client, factory)
    factory.staff("coordinador", "usuario_del_cliente", tenant_id=tid)                  # `account_sync` solo entrega las empresas que usa alguna cuenta: sin esto la fila ni viaja
    before = next(t for t in account_sync.snapshot(db)["tenants"] if t["id"] == tid)
    assert (before["contact_name"], before["contact_email"], before["contact_phone"]) == ("Ana Pérez", EMAIL, MOBILE)          # antes de suprimir, la nube entrega la copia
    client.post(f"/api/crm/contacts/{ana['id']}/erase", json={"reason": "x", "confirm_name": "Ana Pérez"})
    db.expire_all()
    payload = copy.deepcopy(account_sync.snapshot(db))                                  # lo que la nube entrega a un servidor local
    row = next(t for t in payload["tenants"] if t["id"] == tid)
    assert (row["contact_name"], row["contact_email"], row["contact_phone"]) == (None, None, None)
    t = db.get(m.Tenant, tid)                                                           # el servidor local todavía tiene la copia vieja
    t.contact_name, t.contact_email, t.contact_phone = "Ana Pérez", EMAIL, MOBILE
    db.commit()
    account_sync.apply(db, payload)
    db.commit()
    db.expire_all()
    t = db.get(m.Tenant, tid)
    assert (t.contact_name, t.contact_email, t.contact_phone) == (None, None, None)     # aplicar la carga vacía SÍ sobrescribe: la supresión llega al servidor local


def test_erase_account_removes_contacts_notes_history_and_the_mirror_but_keeps_the_client(client, factory, crm_on, db):
    a, tid, ana, beto = _scenario(client, factory)
    url = f"/api/crm/accounts/{a['id']}/erase"
    assert client.post(url, json={"reason": "cierre", "confirm_name": "Otro Nombre"}).status_code == 400
    r = client.post(url, json={"reason": "cierre", "confirm_name": "cliente uno"})
    assert r.status_code == 200 and r.json()["counts"]["contacts"] == 2 and r.json()["counts"]["accounts"] == 1
    db.expire_all()
    assert db.get(m.CrmAccount, a["id"]) is None and db.query(m.CrmContact).count() == 0 and db.query(m.CrmNote).count() == 0 and db.query(m.CrmChangeLog).count() == 0
    t = db.get(m.Tenant, tid)
    assert t is not None and t.name == "Cliente Uno" and (t.contact_name, t.contact_email, t.contact_phone) == (None, None, None)          # el cliente de la plataforma sigue
    audit = db.query(m.AuditAction).filter_by(action="erase", entity="crm_account").one()
    assert "cierre" in audit.detail and not any(p in f"{audit.entity_name} {audit.detail}".lower() for p in PERSONAL)


def test_erasing_a_contact_without_any_other_trace_still_works(client, factory, crm_on, db):
    staff_client(client, factory, "admin", "adm_solo")
    a = new_account(client)
    c = new_contact(client, a["id"], "Solo", "Contacto")
    r = client.post(f"/api/crm/contacts/{c['id']}/erase", json={"reason": "x", "confirm_name": "Solo Contacto"})
    assert r.status_code == 200 and r.json()["counts"]["tenant_fields"] == 0 and r.json()["counts"]["review"] == {"description": False, "general_notes": 0}
    assert client.post(f"/api/crm/contacts/{c['id']}/erase", json={"reason": "x", "confirm_name": "Solo Contacto"}).status_code == 404          # ya no existe
