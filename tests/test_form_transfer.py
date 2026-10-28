"""Exportar / importar un formulario web entre entornos (orden del 23-oct-2026). Copia fiel del diseño, nunca datos personales ni claves, todo o nada, solo admin."""
import io
import json
import zipfile

import pytest
from PIL import Image

from app.models import Event, FormDiscountCode, FormSubmission, WebForm
from app.storage import badge_asset_key, get_storage
from tests.conftest import login


def _png(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(buf, "PNG")
    return buf.getvalue()


def _upload(client, ev, data, name="logo.png"):
    r = client.post(f"/api/events/{ev.id}/forms-upload-image", files={"file": (name, data, "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["storage_path"]


@pytest.fixture()
def origin(client, factory, db):
    """Formulario completo en el evento de ORIGEN (cliente «acme»): imágenes, condición, opciones, un campo opcional, clave, pre-llenado de otro evento,
    redirección al entorno de origen, cupo, calendario, una inscripción con datos personales y un código de descuento."""
    factory.staff("admin", "adm")
    ev = factory.event("en_proceso", tenant_id="acme")
    other = factory.event("en_proceso", tenant_id="acme")
    login(client, "adm")
    form = client.post(f"/api/events/{ev.id}/forms", json={"name": "Congreso Cundi 2026"}).json()
    logo, banner = _upload(client, ev, _png()), _upload(client, ev, _png((10, 120, 40)), "banner.png")
    fields = {
        "cedula": {"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True},
        "nombres": {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
        "talla": {"id": "talla", "type": "select", "label": "Talla de camisa", "options": ["S", "M", "L"], "sync": True},
        "vegano": {"id": "vegano", "type": "radio", "label": "¿Menú vegano?", "options": ["Sí", "No"]},
        "alergia": {"id": "alergia", "type": "text_long", "label": "Alergias", "show_if": {"field": "vegano", "op": "equals", "value": "Sí"}},
        "titulo": {"id": "titulo", "type": "heading", "content": "Bienvenidos al congreso"},
        "foto": {"id": "foto", "type": "image", "src": banner, "width": 80, "alt": "Banner"},
    }
    design = {"theme": {"title": "Congreso Cundi", "logo": logo, "bg_image": logo, "accent": "#123456", "font": "Roboto"},
              "fields": fields, "rows": [{"items": ["titulo"]}, {"items": ["cedula", "nombres"]}, {"items": ["talla", "vegano"], "align": "center"}, {"items": ["alergia"]}, {"items": ["foto"]}]}
    settings = {"security": {"enabled": True, "type": "code", "code": "CLAVESECRETA9"}, "prefill": {"mode": "cedula", "source": f"event:{other.id}"},
                "thanks": {"mode": "redirect", "url": "https://golden-staging-298291650070.web.app/gracias", "title": "Gracias", "text": "Te esperamos", "image": logo},
                "closed_template": {"title": "Cerrado", "text": "Ya no hay cupo", "image": banner}, "feed": "realtime", "language": "es"}
    r = client.put(f"/api/events/{ev.id}/forms/{form['id']}", json={"design": design, "settings": settings})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/events/{ev.id}/forms/{form['id']}/status", json={"manual_status": "activo", "capacity": 50})
    assert r.status_code == 200, r.text
    row = db.query(WebForm).filter_by(id=form["id"]).one()
    db.add(FormSubmission(form_id=row.id, event_id=ev.id, data_json=json.dumps({"cedula": "79123456", "nombres": "Persona Real", "correo": "persona.real@correo.com"}), status="confirmed", is_test=False))
    db.add(FormDiscountCode(form_id=row.id, discount_id="d1", code="DESC2026SECRETO", max_uses=1))
    db.commit()
    db.refresh(row)
    return ev, row


def _export(client, ev, form):
    r = client.get(f"/api/events/{ev.id}/forms/{form.id}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return r.content


def _import(client, ev, data, preview=False):
    url = f"/api/events/{ev.id}/forms-import" + ("/preview" if preview else "")
    return client.post(url, files={"file": ("f.zip", data, "application/zip")})


# ---------------------------------------------------------------------------------------------------- 1) ida y vuelta fiel, queda en pruebas
def test_export_then_import_in_another_event_of_another_client_is_a_faithful_copy_in_testing_mode(client, factory, db, origin):
    ev, form = origin
    data = _export(client, ev, form)
    z = zipfile.ZipFile(io.BytesIO(data))
    assert set(z.namelist()) == {"version", "formulario.json", "LEEME.txt", "imagenes/img1.png", "imagenes/img2.png"}      # logo y banner, cada uno una vez
    assert z.read("version") == b"1"
    leeme = z.read("LEEME.txt").decode("utf-8")
    assert "QUÉ NO CONTIENE" in leeme and "Cupo en el origen: 50" in leeme and "la clave NO se lleva" in leeme

    dest = factory.event("en_proceso", tenant_id="cundi")                      # producción: otro evento y otro cliente
    dest.set_optional_labels({"opcional_1": "Empresa"})
    db.commit()
    pv = _import(client, dest, data, preview=True)
    assert pv.status_code == 200, pv.text
    p = pv.json()
    assert p["summary"].startswith("Se creará el formulario «Congreso Cundi 2026 (importado)» con 5 campos") and "2 imágenes" in p["summary"]
    assert p["optional_created"] == ["Talla de camisa"] and p["optional_reused"] == []
    assert db.query(WebForm).filter_by(event_id=dest.id).count() == 0                  # la vista previa no crea nada
    r = _import(client, dest, data)
    assert r.status_code == 200, r.text
    new = db.query(WebForm).filter_by(event_id=dest.id).one()
    db.refresh(dest)
    assert new.id != form.id and new.name == "Congreso Cundi 2026 (importado)" and new.slug == "congreso-cundi-2026-importado"
    assert new.manual_status == "pruebas" and new.capacity is None and new.use_schedule is False and new.test_key != form.test_key
    assert dest.get_optional_labels() == {"opcional_1": "Empresa", "opcional_2": "Talla de camisa"}

    src_d, new_d = json.loads(form.design_json), json.loads(new.design_json)
    assert new_d["rows"] == src_d["rows"]                                                   # mismo orden y alineación
    assert set(new_d["fields"]) == set(src_d["fields"])
    for fid, f in src_d["fields"].items():
        g = new_d["fields"][fid]
        for k in ("type", "label", "options", "show_if", "content", "required", "width", "alt"):
            assert g.get(k) == f.get(k), (fid, k)
    assert new_d["fields"]["talla"]["key"] == "opcional_2" and new_d["fields"]["cedula"]["key"] == "id"
    for k in ("title", "accent", "font"):
        assert new_d["theme"][k] == src_d["theme"][k]
    # imágenes: en el almacenamiento del cliente destino, con los mismos bytes
    st = get_storage()
    for path, src_path in ((new_d["theme"]["logo"], src_d["theme"]["logo"]), (new_d["fields"]["foto"]["src"], src_d["fields"]["foto"]["src"])):
        assert path.startswith("cundi/") and path != src_path
        assert st.get(badge_asset_key("cundi", path.split("/", 1)[1])) == st.get(badge_asset_key("acme", src_path.split("/", 1)[1]))
    s = json.loads(new.settings_json)
    assert s["security"]["enabled"] is False and s["security"]["code"] == ""               # la clave se vuelve a poner a mano
    assert s["prefill"] == {"mode": "none", "source": "event"}                              # el pre-llenado de otro evento no se lleva
    assert s["thanks"]["mode"] == "template" and s["thanks"]["url"] == "" and s["thanks"]["text"] == "Te esperamos" and s["thanks"]["image"].startswith("cundi/")
    assert s["closed_template"]["text"] == "Ya no hay cupo" and s["feed"] == "realtime"
    # se ve: la página pública de pruebas del formulario importado abre y sirve sus imágenes
    client.cookies.clear()
    page = client.get(f"/f/{dest.id}/{new.slug}?k={new.test_key}")
    assert page.status_code == 200
    img = client.get(f"/f/{dest.id}/{new.slug}/asset/{new_d['theme']['logo']}?k={new.test_key}")
    assert img.status_code == 200 and img.content == _png()


# ---------------------------------------------------------------------------------------------------- 4) nada de lo prohibido sale en el zip
def test_the_zip_never_carries_personal_data_keys_ids_or_origin_urls(client, origin):
    ev, form = origin
    z = zipfile.ZipFile(io.BytesIO(_export(client, ev, form)))
    text = "\n".join(z.read(n).decode("utf-8") for n in ("version", "formulario.json", "LEEME.txt"))
    forbidden = ["79123456", "Persona Real", "persona.real@correo.com",                    # la inscripción
                 "CLAVESECRETA9", form.test_key, "DESC2026SECRETO",                         # claves y códigos
                 ev.event_code, f"event:{ev.id}", "acme/", '"acme"', "golden-staging", ".web.app", "opcional_", "badge-assets"]
    for bad in forbidden:
        assert bad not in text, bad
    pkg = json.loads(z.read("formulario.json"))
    assert set(pkg) == {"formato", "version", "nombre", "diseno", "ajustes", "campos_opcionales", "seguridad", "cupo_en_origen", "usaba_calendario", "avisos"}
    assert pkg["seguridad"] == {"tipo": "code", "activada_en_origen": True}
    assert "id" not in pkg and "event_id" not in json.dumps(pkg)


# ---------------------------------------------------------------------------------------------------- 2) dos veces: sin duplicar campos ni chocar slugs
def test_importing_twice_reuses_optional_fields_and_gets_a_new_slug(client, factory, db, origin):
    ev, form = origin
    data = _export(client, ev, form)
    dest = factory.event("en_proceso", tenant_id="cundi")
    assert _import(client, dest, data).status_code == 200
    second = _import(client, dest, data)
    assert second.status_code == 200, second.text
    assert second.json()["optional_created"] == [] and second.json()["optional_reused"] == ["Talla de camisa"]
    db.refresh(dest)
    assert dest.get_optional_labels() == {"opcional_1": "Talla de camisa"}
    slugs = sorted(f.slug for f in db.query(WebForm).filter_by(event_id=dest.id))
    assert slugs == ["congreso-cundi-2026-importado", "congreso-cundi-2026-importado-2"]
    # importar en el MISMO evento de origen tampoco choca con el original
    assert _import(client, ev, data).status_code == 200


# ---------------------------------------------------------------------------------------------------- 3) archivos dañados o maliciosos: se rechazan, nada a medias
def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_broken_or_malicious_files_are_rejected_with_a_clear_message_and_nothing_is_left(client, factory, db, origin):
    ev, form = origin
    good = zipfile.ZipFile(io.BytesIO(_export(client, ev, form)))
    parts = {n: good.read(n) for n in good.namelist()}
    dest = factory.event("en_proceso", tenant_id="cundi")
    cases = {
        "no es zip": (b"esto no es un zip", "no es un .zip válido"),
        "versión desconocida": (_zip({**parts, "version": b"99"}), "versión de formato que esta aplicación no conoce"),
        "json roto": (_zip({**parts, "formulario.json": b"{roto"}), "formulario.json está roto"),
        "imagen falsa": (_zip({**parts, "imagenes/img1.png": b"<script>alert(1)</script>"}), "no es una imagen válida"),
        "imagen con otra extensión": (_zip({**parts, "imagenes/img1.png": _jpg()}), "no es realmente una imagen PNG"),
        "archivo extraño": (_zip({**parts, "../../etc/passwd": b"x"}), "no corresponde a un formulario exportado"),
        "svg": (_zip({**parts, "imagenes/img3.svg": b"<svg onload='x'/>"}), "no corresponde a un formulario exportado"),
        "zip bomb": (_zip({**parts, "formulario.json": b" " * (50 * 1024 * 1024)}), "es demasiado grande"),
        "falta una imagen": (_zip({k: v for k, v in parts.items() if k != "imagenes/img2.png"}), "falta la imagen"),
        "diseño inválido": (_zip({**parts, "formulario.json": json.dumps({**json.loads(parts["formulario.json"]), "diseno": {"fields": {"x": {"type": "malware"}}}}).encode()}), "Tipo de campo no válido"),
    }
    labels_before = dest.get_optional_labels()
    for case, (data, msg) in cases.items():
        for preview in (True, False):
            r = _import(client, dest, data, preview=preview)
            assert r.status_code == 400 and msg in r.json()["detail"] and r.json()["detail"].startswith("El archivo no se puede importar"), (case, r.text)
    db.refresh(dest)
    assert db.query(WebForm).filter_by(event_id=dest.id).count() == 0 and dest.get_optional_labels() == labels_before


def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "JPEG")
    return buf.getvalue()


def test_a_failure_after_uploading_images_removes_them_and_creates_nothing(client, factory, db, origin, monkeypatch):
    ev, form = origin
    data = _export(client, ev, form)
    dest = factory.event("en_proceso", tenant_id="cundi")
    st = get_storage()
    stored = []
    real_put = type(st).put
    monkeypatch.setattr(type(st), "put", lambda self, key, d: (stored.append(key), real_put(self, key, d))[1])

    def boom(*a, **k):
        raise RuntimeError("falla simulada al crear el formulario")
    monkeypatch.setattr("app.routers.form_transfer._unique_slug", boom)
    with pytest.raises(RuntimeError):
        _import(client, dest, data)
    assert len(stored) == 2 and not any(st.exists(k) for k in stored)                       # las imágenes subidas se borraron
    db.expire_all()
    assert db.query(WebForm).filter_by(event_id=dest.id).count() == 0
    assert db.query(Event).filter_by(id=dest.id).one().get_optional_labels() == {}           # ni el campo opcional


# ---------------------------------------------------------------------------------------------------- 5) solo admin y super_admin
def test_only_admins_can_export_or_import_and_the_buttons_are_hidden_for_others(client, factory, db, origin):
    ev, form = origin
    data = _export(client, ev, form)
    assert client.get(f"/api/events/{ev.id}/forms-transfer/allowed").json() == {"allowed": True}
    factory.staff("coordinador", "coord")
    factory.authorize(ev, db.query(__import__("app.models", fromlist=["StaffUser"]).StaffUser).filter_by(username="coord").one())
    client.cookies.clear()
    login(client, "coord")
    assert client.get(f"/api/events/{ev.id}/forms-transfer/allowed").json() == {"allowed": False}
    assert client.get(f"/api/events/{ev.id}/forms/{form.id}/export").status_code == 403
    assert _import(client, ev, data, preview=True).status_code == 403
    assert _import(client, ev, data).status_code == 403
    page = client.get(f"/kiosk/{ev.id}/formularios").text
    assert 'id="importCard" hidden' in page                                                  # escondido hasta que el servidor diga que sí
    factory.staff("super_admin", "sup")
    client.cookies.clear()
    login(client, "sup")
    assert client.get(f"/api/events/{ev.id}/forms-transfer/allowed").json() == {"allowed": True}
    assert client.get(f"/api/events/{ev.id}/forms/{form.id}/export").status_code == 200


def test_the_existing_forms_list_and_duplicate_still_work_as_before(client, origin):
    ev, form = origin
    assert client.get(f"/api/events/{ev.id}/forms").status_code == 200
    dup = client.post(f"/api/events/{ev.id}/forms/{form.id}/duplicate")
    assert dup.status_code == 200 and dup.json()["name"] == "Congreso Cundi 2026 (copia)"
