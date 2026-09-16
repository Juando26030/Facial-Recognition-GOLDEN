import numpy as np
import pytesseract
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_event_for_staff, require_role
from app.biometrics import BiometricEngine
from app.database import get_db
from app.models import StaffUser
from app.mrz_ocr import extract_mrz_lines
from app.mrz_parser import parse_mrz_td1

router = APIRouter()

# Sprint 2.2 Fase C (2026-09-16): la foto puede llegar apaisada (horizontal) o vertical según
# cómo la haya sostenido quien la tomó — se prueba OCR en las 4 rotaciones posibles y se usa la
# PRIMERA que produzca una lectura MRZ válida (checksum ICAO correcto), en vez de asumir una sola
# orientación fija. `np.rot90(arr, k)` gira 90°*k en sentido antihorario.
_ROTATIONS = (0, 1, 2, 3)


@router.post("/events/{event_id}/cedula-mrz-scan")
async def scan_cedula_mrz(
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
    event = get_event_for_staff(event_id, db, staff)  # valida acceso al evento, no se usa más

    img_array = BiometricEngine.process_image_stream(await file.read())

    best_result = None
    any_lines_detected = False
    for k in _ROTATIONS:
        rotated = np.rot90(img_array, k) if k else img_array
        try:
            lines = extract_mrz_lines(rotated)
        except pytesseract.pytesseract.TesseractNotFoundError:
            # No es un problema de la foto — el binario de Tesseract no está instalado en este
            # servidor (`apt install tesseract-ocr` en la VM, ver CLAUDE.md/requirements.txt). Sin
            # este catch, esto se ve como un 500 críptico en vez de decir claramente qué falta.
            raise HTTPException(
                status_code=503,
                detail="El servidor no tiene instalado el motor de OCR (Tesseract) — contacta a soporte técnico.",
            )
        if len(lines) < 3:
            continue
        any_lines_detected = True
        result = parse_mrz_td1(lines[-3], lines[-2], lines[-1])
        if result["valid"]:
            best_result = result
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
