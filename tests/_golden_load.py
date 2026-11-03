"""Casos de la carga masiva y su volcado canónico (lo usa tests/test_rendimiento.py; con GOLDEN_OUT=<archivo> se ejecuta contra el código ANTERIOR para guardar el resultado de referencia)."""
import io
import json
import os
from datetime import date

from openpyxl import Workbook

from app.models import AccessLog, EventAttendee, PersonChange, SuppressedPerson, User
from app import consent as consent_mod

HEAD = ["id", "nombres", "apellidos", "cargo", "entidad", "telefono", "correo", "tipo de asistente", "categoria", "certificado", "opcional_1", "Fecha nac. cliente"]
ROWS = [
    # nueva, completa
    ["1001", "Ana", "Mora", "Gerente", "ACME", "3001112233", "ana@acme.com", "VIP", "General, Zona A", "si", "Talla M", "10/03/1990"],
    # existente en la base con otros datos y con inscripción previa (se actualiza)
    ["1002", "Beto", "Paz", "Analista", "Beta SA", "3002223344", "beto@beta.com", "Invitado", "Zona B", "", "Talla L", ""],
    # repetida dentro del archivo (queda lo de la última fila)
    ["1003", "Cata", "Primera", "", "", "", "", "", "", "", "", ""],
    ["1003", "Cata", "Segunda", "Directora", "", "", "", "", "", "", "", ""],
    # sin cédula
    ["", "Sin", "Cedula", "", "", "", "", "", "", "", "", ""],
    # suprimida por habeas data
    ["1004", "Supri", "Mida", "", "", "", "", "", "", "", "", ""],
    # datos dudosos: sin nombre, correo y teléfono raros
    ["1005", "", "", "", "", "tel-raro", "no-es-correo", "", "", "", "", ""],
    # cédula que Excel volvió número con decimales y con puntos
    ["1.006", "Dora", "Puntos", "", "", "", "", "", "", "", "", ""],
    # fecha de nacimiento ilegible → solo es un campo personalizado, no cambia nada del resto
    ["1007", "Eli", "Fecha", "", "", "", "", "", "Zona A", "", "", "no-es-fecha"],
    # existente con inscripción y categorías previas que NO vienen en el archivo
    ["1008", "Fito", "Previo", "", "", "", "", "", "", "", "", ""],
]


def xlsx_bytes(rows=ROWS, head=HEAD):
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def prepare(db, ev):
    """Estado previo: 1002 y 1008 ya existen (1008 con inscripción y categorías), 1004 pidió la supresión."""
    db.add(User(id="1002", tenant_id=ev.tenant_id, first_name="Viejo", last_name="Nombre", role="Cargo viejo", birth_date=date(1985, 5, 5)))
    db.add(User(id="1008", tenant_id=ev.tenant_id, first_name="Fito", last_name="Previo", entity="Vieja"))
    db.flush()
    att = EventAttendee(event_id=ev.id, user_id="1008", tenant_id=ev.tenant_id)
    att.set_categories(["General"])
    db.add(att)
    db.add(SuppressedPerson(tenant_id=ev.tenant_id, cedula_hash=consent_mod.cedula_hash("1004")))
    ev.set_categories(["General", "Zona B"])
    db.commit()


def dump(db, ev, response):
    db.expire_all()
    users = []
    for u in db.query(User).filter(User.tenant_id == ev.tenant_id):
        users.append({"id": u.id, "first_name": u.first_name, "last_name": u.last_name, "role": u.role, "entity": u.entity, "phone": u.phone, "email": u.email, "opt_1": u.opt_1,
                      "extras": u.get_extras(), "birth_date": u.birth_date.isoformat() if u.birth_date else None, "bio": u.is_biometric_enabled})
    atts = [{"user_id": a.user_id, "categories": a.get_categories(), "certificate": bool(a.certificate)} for a in db.query(EventAttendee).filter_by(event_id=ev.id)]
    # Orden DETERMINISTA, en Python y por el texto de la cédula: un ORDER BY de la base depende de su colación (en una base con colación de idioma, como la de CI, «1.006» queda entre
    # «1005» y «1007»; en una con colación «C» o ICU por defecto queda primero) y la prueba comparaba el orden en vez de los datos.
    users.sort(key=lambda r: r["id"])
    atts.sort(key=lambda r: r["user_id"])
    changes = [{"user_id": c.user_id, "kind": c.kind, "old": c.old_value, "new": c.new_value} for c in db.query(PersonChange).filter_by(event_id=ev.id).order_by(PersonChange.id)]       # por número: no depende de la colación
    db.refresh(ev)
    return {"response": {k: response[k] for k in ("message", "count", "errors", "columns", "birth", "optional_labels")}, "users": users, "attendees": atts, "changes": changes,
            "event_categories": ev.get_categories(), "optional_labels": ev.get_optional_labels(), "roster_uploaded": ev.roster_uploaded,
            "logs": db.query(AccessLog).filter_by(event_id=ev.id).count()}


def golden_run(client, factory, db):
    from tests.conftest import login
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    prepare(db, ev)
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "field_labels": json.dumps({"opcional_1": "Talla"})},
                    files={"roster_file": ("p.xlsx", xlsx_bytes(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    return ev, r.json()


def test_make_golden(client, factory, db):
    out = os.getenv("GOLDEN_OUT")
    if not out:
        import pytest
        pytest.skip("solo para generar el resultado de referencia")
    ev, resp = golden_run(client, factory, db)
    d = dump(db, ev, resp)
    # un segundo envío del MISMO archivo (reintento): el resultado también se guarda
    from tests.conftest import login  # noqa: F401
    r2 = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", xlsx_bytes(), "application/octet-stream")})
    assert r2.status_code == 200, r2.text
    d["retry"] = dump(db, ev, r2.json())
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
