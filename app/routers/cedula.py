import numpy as np
import pytesseract
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.biometrics import BiometricEngine
from app.database import get_db
from app import cedula_near, event_archive, name_index
from app.models import EventAttendee, StaffUser, User
from app.mrz_ocr import VARIANTS, extract_mrz_lines
from app.mrz_parser import parse_mrz_td1

router = APIRouter()

# Sprint 2.2 Fase C (2026-09-16): la foto puede llegar apaisada (horizontal) o vertical según
# cómo la haya sostenido quien la tomó — se prueba OCR en las 4 rotaciones posibles y se usa la
# PRIMERA que produzca una lectura MRZ válida (checksum ICAO correcto), en vez de asumir una sola
# orientación fija. `np.rot90(arr, k)` gira 90°*k en sentido antihorario.
_ROTATIONS = (0, 1, 2, 3)


@router.post("/events/{event_id}/cedula-mrz-scan")
def scan_cedula_mrz(
    event_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    staff: StaffUser = Depends(require_role("digitador")),
):
    """Lee por OCR la zona MRZ del reverso de la cédula colombiana nueva (Sprint 2 Parte 2,
    Historia 2.3) — el QR de esa cédula viene encriptado por la Registraduría y NO se intenta
    decodificar (ver CLAUDE.md), así que este es el único camino automático para esa cédula:
    una foto del reverso en vez de un escaneo de código de barras/QR. Mismo mínimo de rol que
    `checkin-cedula` (quien opera el registro el día del evento). No hace ningún registro por sí
    mismo — solo devuelve la cédula/nombre extraídos para que el frontend siga el mismo flujo de
    dos pasos (cédula exacta, luego nombre) que ya usa la cédula vieja."""
    get_event_for_staff(event_id, db, staff)  # valida acceso al evento, no se usa más

    img_array = BiometricEngine.process_image_stream(file.file.read())

    best_result = None
    any_lines_detected = False
    for k in _ROTATIONS:
        rotated = np.rot90(img_array, k) if k else img_array
        for variant in range(len(VARIANTS)):
            try:
                lines = extract_mrz_lines(rotated, variant)
            except pytesseract.pytesseract.TesseractNotFoundError:
                # No es un problema de la foto — el binario de Tesseract no está instalado en este
                # servidor (`apt install tesseract-ocr` en la VM, ver CLAUDE.md/requirements.txt). Sin
                # este catch, esto se ve como un 500 críptico en vez de decir claramente qué falta.
                raise HTTPException(
                    status_code=503,
                    detail="El servidor no tiene instalado el motor de OCR (Tesseract) — contacta a soporte técnico.",
                )
            if len(lines) < 3:
                if variant == 0:
                    break          # con la preparación normal no hay 3 líneas: esta no es la orientación; no se gastan más variantes aquí
                continue
            any_lines_detected = True
            result = parse_mrz_td1(lines[-3], lines[-2], lines[-1])
            if result["valid"]:
                best_result = result
                break              # orientación candidata (3 líneas) pero sin validar: se prueba la siguiente preparación de la imagen (reflejos, fondo con tramas)
        if best_result is not None:
            break

    if best_result is None:
        if not any_lines_detected:
            raise HTTPException(
                status_code=422,
                detail="No se detectó la zona MRZ en la foto — toma de nuevo el reverso de la cédula bien encuadrado y con buena luz.",
            )
        raise HTTPException(
            status_code=422,
            detail="La foto no se pudo leer con confianza (no coincide el dígito verificador) — intenta tomarla de nuevo.",
        )

    return {"id": best_result["id"], "first_name": best_result["first_name"], "last_name": best_result["last_name"]}


NEAR_LIMIT = 6


@router.post("/events/{event_id}/cedula-near")
def cedula_near_candidates(event_id: int, data: dict = Body(...), db: Session = Depends(get_db),
                           staff: StaffUser = Depends(require_role("digitador"))):
    """24-nov-2026: la cámara leyó la cédula A MEDIAS (reflejo, poca luz) → personas PARECIDAS para que el operador elija. NUNCA acredita: la elegida
    entra por `checkin-cedula` (coincidencia exacta). Por número: a un error de lectura (app/cedula_near.py), por igualdad sobre el índice. Por nombre:
    el mismo índice del «cédula no encontrada» (app/name_index.py). Nada de lo leído va a los registros."""
    event = get_event_for_staff(event_id, db, staff)
    event_archive.require_data_open(event, staff)          # lee personas del cliente: con la base archivada, solo super_admin
    read = cedula_near.clean(data.get("cedula"))
    name = f"{str(data.get('first_name') or '')} {str(data.get('last_name') or '')}".strip()[:200]
    by_number = []
    options = cedula_near.variants(read)
    if options:
        rows = (db.query(User.id, User.first_name, User.last_name, User.entity)
                .filter(User.tenant_id == event.tenant_id, User.id.in_(options)).limit(50).all())
        in_event = {uid for (uid,) in db.query(EventAttendee.user_id).filter(EventAttendee.event_id == event.id,
                                                                              EventAttendee.user_id.in_([r[0] for r in rows])).all()} if rows else set()
        rank = {v: i for i, v in enumerate(options)}
        rows = sorted(rows, key=lambda r: (r[0] not in in_event, rank.get(r[0], 9999)))          # primero las del evento, luego las más parecidas
        by_number = [{"id": r[0], "first_name": r[1], "last_name": r[2], "entity": r[3], "in_event": r[0] in in_event} for r in rows[:NEAR_LIMIT]]
    by_name = name_index.find(db, event.tenant_id, name, NEAR_LIMIT)[0] if name else []
    seen = {c["id"] for c in by_number}
    by_name = [c for c in by_name if c["id"] not in seen]
    return {"by_number": by_number, "by_name": by_name}
