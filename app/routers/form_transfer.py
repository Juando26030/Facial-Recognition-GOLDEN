"""Exportar / importar un formulario web entre entornos (orden del 23-oct-2026: llevar un formulario diseñado en staging a producción).

Solo CONFIGURACIÓN y DISEÑO (Ley 1581/2012). El .zip lleva:
  - `formulario.json`: diseño completo (tema, filas, campos, condiciones, pago, acompañantes) y ajustes (plantillas de cerrado y de agradecimiento,
    cupos por reglas, reembolsos, cómo alimenta la base, idioma…), más los NOMBRES de los campos opcionales del evento que usa.
  - `version` y `LEEME.txt`; las imágenes del formulario en `imagenes/`.
NUNCA lleva: inscripciones, personas, archivos subidos, pagos, invitaciones, códigos de descuento, la clave de seguridad, la clave de pruebas (`test_key`),
ids internos ni código del evento, el cliente de origen ni URLs del entorno de origen. Un pre-llenado desde otro evento o desde una base aparte no se lleva.

Importar crea SIEMPRE una copia nueva («<nombre> (importado)», slug único) en estado «pruebas», sin cupo ni calendario, y sin seguridad por clave: se revisa
y se activa a mano. Todo o nada: si algo falla, no queda ni el formulario, ni los campos opcionales, ni las imágenes subidas.
Solo admin y super_admin. Bitácora: una línea en el log `golden.form_transfer` (quién, cuándo, qué formulario y en qué evento; sin datos personales).
"""
import io
import json
import logging
import re
import secrets
import unicodedata
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image
from sqlalchemy.orm import Session

from app import formlib, formsvc, safe_limits
from app.auth import ROLE_HIERARCHY, effective_roles, get_event_for_staff, require_role
from app.database import get_db
from app.models import Event, StaffUser, WebForm
from app.routers.forms import _detail, _get_form, _unique_slug
from app.storage import badge_asset_key, get_storage

log = logging.getLogger("golden.form_transfer")
router = APIRouter()
ADMIN = require_role("admin")
VIEW = require_role("coordinador")

FORMAT = "goldenweb-formulario"
VERSION = 1
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024          # suma de lo que se descomprime (contra «zip bomb»: se cuenta lo que de verdad sale, no lo que dice el zip)
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8_000_000                  # mismo tope que «subir imagen» del editor
MAX_ENTRIES = 60
IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF"}
NAME_RE = re.compile(r"^(version|formulario\.json|LEEME\.txt|imagenes/img[0-9]{1,3}\.(png|jpg|jpeg|webp|gif))$")
ZIP_REF = "zip:"                             # en el json, una imagen se nombra «zip:imagenes/img1.png»
OPT_REF = "@campo_opcional:"                 # y un campo opcional del evento, por su posición en «campos_opcionales» (nunca el opcional_N de origen)
STAGING_HINTS = ("golden-staging", ".web.app", ".run.app", "localhost", "127.0.0.1")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().casefold()


def _is_admin(staff: StaffUser) -> bool:
    return max(ROLE_HIERARCHY[r] for r in effective_roles(staff)) >= ROLE_HIERARCHY["admin"]


def _origin_hosts(request: Request) -> tuple:
    return STAGING_HINTS + (request.url.hostname or "",)


# ------------------------------------------------------------------------------------------------ exportar
def _image_refs(design: dict, settings: dict):
    """(dueño, clave) de cada lugar donde el formulario guarda una imagen: logo y fondo del tema, imagen de «cerrado», del agradecimiento y campos imagen."""
    yield design["theme"], "logo"
    yield design["theme"], "bg_image"
    yield settings["closed_template"], "image"
    yield settings["thanks"], "image"
    if settings.get("identify"):
        yield settings["identify"], "image"
    yield from formlib.image_refs(design)          # imágenes de los elementos imagen y de sus variantes


def build_export(db: Session, event: Event, form: WebForm, request: Request) -> tuple:
    design = json.loads(json.dumps(formsvc.get_design(form)))
    settings = json.loads(json.dumps(formsvc.get_settings(form)))
    notes, images = [], {}
    hosts = _origin_hosts(request)

    # imágenes: solo las de ESTE cliente, que existen en el almacenamiento; una URL externa se deja si no es del entorno de origen
    by_path = {}
    for owner, key in _image_refs(design, settings):
        value = str(owner.get(key) or "")
        if not value:
            continue
        m = re.fullmatch(r"(?:/api/badge-assets/)?([^/]+)/([A-Za-z0-9._-]+)", value)
        ext = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        if m and m.group(1) == event.tenant_id and ext in IMAGE_FORMATS:
            if value not in by_path:
                try:
                    data = get_storage().get(badge_asset_key(event.tenant_id, m.group(2)))
                except Exception:
                    data = None
                if not data:
                    notes.append("Una imagen del formulario no se encontró en el almacenamiento y no se llevó.")
                    owner[key] = ""
                    continue
                name = f"imagenes/img{len(images) + 1}.{ext}"
                images[name] = data
                by_path[value] = ZIP_REF + name
            owner[key] = by_path[value]
        elif re.match(r"^https?://", value) and not any(h and h in value for h in hosts):
            owner[key] = value
        else:
            owner[key] = ""
            notes.append("Una imagen apuntaba al entorno de origen o a otro cliente y no se llevó.")

    # campos opcionales del evento: por NOMBRE (en destino se reutiliza el del mismo nombre o se crea uno)
    labels = event.get_optional_labels()
    optional = []
    for f in design["fields"].values():
        k = f.get("key")
        if k and k.startswith("opcional_"):
            optional.append({"nombre": labels.get(k) or f.get("label") or k})
            f["key"] = f"{OPT_REF}{len(optional) - 1}"

    # seguridad: solo el TIPO (la clave se vuelve a poner en destino)
    sec = settings.get("security") or {}
    security_info = {"tipo": sec.get("type", "code"), "activada_en_origen": bool(sec.get("enabled"))}
    if sec.get("type") == "code":
        if sec.get("enabled"):
            notes.append("El formulario tenía seguridad por palabra o código: la clave NO se lleva. Vuelve a ponerla en el destino.")
        settings["security"] = {"enabled": False, "type": "code", "code": ""}
    # pre-llenado desde otro evento o desde una base subida aparte: no se lleva
    pre = settings.get("prefill") or {}
    if pre.get("source") != "event":
        if pre.get("mode") != "none":
            notes.append("El pre-llenado venía de otro evento o de una base subida aparte: queda sin configurar. Revísalo en el destino.")
        settings["prefill"] = {"mode": "none", "source": "event"}
    # redirección al terminar que apunta al entorno de origen
    thanks = settings.get("thanks") or {}
    if thanks.get("url") and any(h and h in thanks["url"] for h in hosts):
        thanks.update({"mode": "template", "url": ""})
        notes.append("La redirección al terminar apuntaba al entorno de origen: queda la plantilla de agradecimiento.")
    if any(f.get("type") == formlib.PAYMENT_TYPE and (f.get("pay") or {}).get("codes") for f in design["fields"].values()):
        notes.append("El formulario usa códigos de descuento: los códigos NO se llevan. Genéralos de nuevo en el destino.")

    package = {"formato": FORMAT, "version": VERSION, "nombre": form.name, "diseno": design, "ajustes": settings,
               "campos_opcionales": optional, "seguridad": security_info, "cupo_en_origen": form.capacity,
               "usaba_calendario": bool(form.use_schedule), "avisos": notes}
    text = json.dumps(package, ensure_ascii=False, indent=1)
    for secret in (form.test_key, sec.get("code") or ""):          # defensa: nada de claves en el archivo
        if secret and len(secret) >= 4 and secret in text:
            raise HTTPException(status_code=500, detail="El formulario contiene su propia clave en un texto: no se puede exportar así.")
    return package, text, images, notes


def _leeme(package: dict, images: dict) -> str:
    lines = [
        "FORMULARIO WEB EXPORTADO (GoldenWeb 2.0)",
        f"Formato: {FORMAT}, versión {VERSION}",
        f"Formulario: {package['nombre']}",
        f"Elementos: {len(package['diseno']['fields'])} · Imágenes: {len(images)} · Campos opcionales del evento: {len(package['campos_opcionales'])}",
        "",
        "QUÉ CONTIENE",
        "- formulario.json: diseño completo (tema, filas, campos, condiciones, pago y acompañantes) y ajustes (cerrado, agradecimiento, cupos por reglas,",
        "  reembolsos, cómo alimenta la base, idioma), y los NOMBRES de los campos opcionales del evento que usa.",
        "- imagenes/: logos, fondos e imágenes del formulario.",
        "",
        "QUÉ NO CONTIENE (se reconfigura en el destino)",
        "- Inscripciones, personas, archivos subidos, pagos, invitaciones ni registros: nunca.",
        "- La clave de seguridad del formulario (solo el tipo), la clave del enlace de pruebas y los códigos de descuento.",
        "- El estado, el calendario y el cupo: el formulario importado queda «En pruebas», sin calendario y sin cupo.",
        f"  Cupo en el origen: {package['cupo_en_origen'] if package['cupo_en_origen'] is not None else 'sin límite'} · Usaba calendario: {'sí' if package['usaba_calendario'] else 'no'}",
        "- Un pre-llenado desde otro evento o desde una base subida aparte.",
        "- Las llaves de pagos (Wompi) son del entorno, no del formulario.",
    ]
    if package["avisos"]:
        lines += ["", "AVISOS DE ESTA EXPORTACIÓN"] + [f"- {n}" for n in package["avisos"]]
    return "\r\n".join(lines) + "\r\n"


@router.get("/events/{event_id}/forms/{form_id}/export")
def export_form(event_id: int, form_id: int, request: Request, db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    event = get_event_for_staff(event_id, db, staff)
    form = _get_form(db, event, form_id)
    package, text, images, _notes = build_export(db, event, form, request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version", str(VERSION))
        z.writestr("formulario.json", text)
        z.writestr("LEEME.txt", _leeme(package, images))
        for name, data in images.items():
            z.writestr(name, data)
    log.info("formulario exportado: formulario %s del evento %s por el usuario %s (%s imágenes)", form.id, event.id, staff.id, len(images))
    fname = f"formulario-{formlib.slugify(form.name)}.zip"
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ------------------------------------------------------------------------------------------------ importar
def _bad(msg: str):
    raise HTTPException(status_code=400, detail=f"El archivo no se puede importar: {msg}")


def read_package(raw: bytes) -> tuple:
    """Valida el .zip completo SIN tocar nada: tamaño, nombres permitidos, lo que de verdad se descomprime, versión, json e imágenes reales."""
    if not raw:
        _bad("está vacío.")
    if len(raw) > MAX_ZIP_BYTES:
        _bad(f"pesa más de {MAX_ZIP_BYTES // (1024 * 1024)} MB.")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        infos = z.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        _bad("no es un .zip válido (¿está dañado?).")
    if len(infos) > MAX_ENTRIES:
        _bad("tiene demasiados archivos.")
    files, total = {}, 0
    for info in infos:
        if info.is_dir():
            continue
        if not NAME_RE.match(info.filename):
            _bad(f"trae un archivo que no corresponde a un formulario exportado ({info.filename[:60]}).")
        limit = MAX_JSON_BYTES if not info.filename.startswith("imagenes/") else MAX_IMAGE_BYTES
        try:
            with z.open(info) as fh:
                data = fh.read(limit + 1)                               # se lee con tope: un zip que dice pesar poco y descomprime mucho se corta aquí
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, NotImplementedError):
            _bad("está dañado (no se pudo descomprimir).")
        if len(data) > limit:
            _bad(f"«{info.filename}» es demasiado grande.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            _bad("descomprimido es demasiado grande.")
        files[info.filename] = data
    if (files.get("version") or b"").strip() != str(VERSION).encode():
        _bad("es de una versión de formato que esta aplicación no conoce.")
    try:
        package = json.loads(files.get("formulario.json") or b"")
    except (ValueError, UnicodeDecodeError):
        _bad("formulario.json está roto (no es un JSON válido).")
    if not isinstance(package, dict) or package.get("formato") != FORMAT or package.get("version") != VERSION:
        _bad("no es un formulario exportado de GoldenWeb (o es de otra versión).")
    for key, kind in (("diseno", dict), ("ajustes", dict), ("campos_opcionales", list), ("nombre", str)):
        if not isinstance(package.get(key), kind):
            _bad(f"formulario.json no tiene «{key}».")
    images = {}
    for name, data in files.items():
        if not name.startswith("imagenes/"):
            continue
        ext = name.rsplit(".", 1)[-1].lower()
        try:
            safe_limits.check_image_dimensions(data)
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                im.verify()
        except Exception:
            _bad(f"«{name}» no es una imagen válida.")
        if fmt != IMAGE_FORMATS[ext]:
            _bad(f"«{name}» no es realmente una imagen {ext.upper()}.")
        images[name] = data
    return package, images


def plan_import(db: Session, event: Event, package: dict, images: dict) -> dict:
    """Calcula TODO lo que se va a crear (sin escribir nada): diseño y ajustes ya validados para este evento, campos opcionales nuevos y reutilizados."""
    design, settings = json.loads(json.dumps(package["diseno"])), json.loads(json.dumps(package["ajustes"]))
    if not isinstance(design.get("fields"), dict) or not isinstance(design.get("theme", {}), dict):
        _bad("el diseño no tiene la forma esperada.")
    for key in ("closed_template", "thanks", "identify"):
        if not isinstance(settings.get(key, {}), dict):
            _bad("los ajustes no tienen la forma esperada.")
        settings.setdefault(key, {})
    design.setdefault("theme", {})
    # campos opcionales: mismo nombre en el destino → se reutiliza; si no, el primer opcional_N libre
    labels = dict(event.get_optional_labels())
    by_name = {_norm(v): k for k, v in labels.items()}
    used = {int(k.split("_")[1]) for k in labels if re.fullmatch(r"opcional_\d+", k)}
    mapping, created, reused = {}, [], []
    for i, item in enumerate(package["campos_opcionales"]):
        name = str((item or {}).get("nombre") or "").strip()[:120] if isinstance(item, dict) else ""
        if not name:
            _bad("un campo opcional no tiene nombre.")
        key = by_name.get(_norm(name))
        if key:
            if labels[key] not in reused:
                reused.append(labels[key])
        else:
            slot = next((n for n in range(1, 31) if n not in used), None)
            if slot is None:
                _bad("el evento destino ya usa sus 30 campos opcionales.")
            used.add(slot)
            key = f"opcional_{slot}"
            labels[key] = name
            by_name[_norm(name)] = key
            created.append(name)
        mapping[f"{OPT_REF}{i}"] = key
    for f in design["fields"].values():
        if not isinstance(f, dict):
            _bad("un campo del diseño no es válido.")
        k = f.get("key")
        if isinstance(k, str) and k.startswith(OPT_REF):
            if k not in mapping:
                _bad("un campo apunta a un campo opcional que no viene en el archivo.")
            f["key"] = mapping[k]
        elif k and k not in formlib.IDENTITY_KEYS:
            f["key"] = None                                           # nunca un opcional_N «crudo» de otro evento
    # imágenes: cada «zip:imagenes/…» debe venir en el zip; se le da un nombre nuevo del cliente destino
    uploads, new_names = {}, {}
    for owner, key in _image_refs(design, {"closed_template": settings["closed_template"], "thanks": settings["thanks"], "identify": settings["identify"]}):
        value = str(owner.get(key) or "")
        if value.startswith(ZIP_REF):
            name = value[len(ZIP_REF):]
            if name not in images:
                _bad(f"falta la imagen «{name}».")
            if name not in new_names:
                new_names[name] = f"{secrets.token_hex(16)}.{name.rsplit('.', 1)[-1].lower()}"
                uploads[new_names[name]] = images[name]
            owner[key] = f"{event.tenant_id}/{new_names[name]}"
        elif value and not re.match(r"^https?://", value):
            owner[key] = ""
    settings["security"] = {"enabled": (settings.get("security") or {}).get("type") == "cedula" and bool((settings.get("security") or {}).get("enabled")),
                            "type": "cedula" if (settings.get("security") or {}).get("type") == "cedula" else "code", "code": ""}
    pre = settings.get("prefill") or {}
    if not isinstance(pre, dict) or pre.get("source") != "event":
        settings["prefill"] = {"mode": "none", "source": "event"}
    try:
        design = formlib.sanitize_design(design, set(labels))
        settings = formlib.sanitize_settings(settings)
    except ValueError as e:
        _bad(str(e))
    name = f"{str(package['nombre']).strip()[:100] or 'Formulario'} (importado)"
    return {"name": name, "design": design, "settings": settings, "labels": labels, "created": created, "reused": reused, "uploads": uploads,
            "elements": len(design["fields"]), "inputs": sum(1 for f in design["fields"].values() if f["type"] in formlib.INPUT_TYPES),
            "notes": [str(n)[:300] for n in package.get("avisos") or [] if isinstance(n, str)][:20], "capacity_hint": package.get("cupo_en_origen")}


def _read_upload(file: UploadFile) -> bytes:
    raw = file.file.read(MAX_ZIP_BYTES + 1)
    if len(raw) > MAX_ZIP_BYTES:
        _bad(f"pesa más de {MAX_ZIP_BYTES // (1024 * 1024)} MB.")
    return raw


def _preview_out(plan: dict) -> dict:
    return {"name": plan["name"], "elements": plan["elements"], "inputs": plan["inputs"], "images": len(plan["uploads"]),
            "optional_created": plan["created"], "optional_reused": plan["reused"], "notes": plan["notes"], "capacity_in_origin": plan["capacity_hint"],
            "summary": f"Se creará el formulario «{plan['name']}» con {plan['inputs']} campos ({plan['elements']} elementos en total) y {len(plan['uploads'])} imágenes, en estado «En pruebas»."}


@router.post("/events/{event_id}/forms-import/preview")
def import_preview(event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Vista previa: valida y cuenta lo que se crearía. No escribe NADA."""
    event = get_event_for_staff(event_id, db, staff)
    package, images = read_package(_read_upload(file))
    return _preview_out(plan_import(db, event, package, images))


@router.post("/events/{event_id}/forms-import")
def import_form(event_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), staff: StaffUser = Depends(ADMIN)):
    """Crea la copia: todo o nada (si algo falla, se borran las imágenes ya subidas y no queda nada en la base)."""
    event = get_event_for_staff(event_id, db, staff)
    package, images = read_package(_read_upload(file))
    plan = plan_import(db, event, package, images)
    stored = []
    try:
        for name, data in plan["uploads"].items():
            key = badge_asset_key(event.tenant_id, name)
            get_storage().put(key, data)
            stored.append(key)
        event.set_optional_labels(plan["labels"])
        form = WebForm(event_id=event.id, name=plan["name"], slug=_unique_slug(db, event.id, plan["name"]), manual_status="pruebas", use_schedule=False,
                       schedule_json=None, capacity=None, design_json=json.dumps(plan["design"]), settings_json=json.dumps(plan["settings"]),
                       test_key=secrets.token_urlsafe(12), created_by_id=staff.id)
        db.add(form)
        db.commit()
    except Exception:
        db.rollback()
        for key in stored:
            try:
                get_storage().delete(key)
            except Exception:
                log.warning("importar formulario: no se pudo borrar una imagen ya subida tras el error")
        raise
    log.info("formulario importado: formulario nuevo %s en el evento %s por el usuario %s (%s imágenes, %s campos opcionales creados)",
             form.id, event.id, staff.id, len(stored), len(plan["created"]))
    return {**_preview_out(plan), "form": _detail(db, form, request)}


@router.get("/events/{event_id}/forms-transfer/allowed")
def transfer_allowed(event_id: int, db: Session = Depends(get_db), staff: StaffUser = Depends(VIEW)):
    """La pantalla de formularios pregunta si muestra «Exportar» e «Importar» (el servidor exige admin igual)."""
    get_event_for_staff(event_id, db, staff)
    return {"allowed": _is_admin(staff)}
