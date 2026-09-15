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
    try:
        lines = extract_mrz_lines(img_array)
    except pytesseract.pytesseract.TesseractNotFoundError:
        # No es un problema de la foto — el binario de Tesseract no está instalado en este
        # servidor (`apt install tesseract-ocr` en la VM, ver CLAUDE.md/requirements.txt). Sin
        # este catch, esto se ve como un 500 críptico en vez de decir claramente qué falta.
        raise HTTPException(
            status_code=503,
            detail="El servidor no tiene instalado el motor de OCR (Tesseract) — contacta a soporte técnico.",
        )
    if len(lines) < 3:
        raise HTTPException(
            status_code=422,
            detail="No se detectó la zona MRZ en la foto — toma de nuevo el reverso de la cédula bien encuadrado, derecho y con buena luz.",
        )

    line1, line2, line3 = lines[-3], lines[-2], lines[-1]
    result = parse_mrz_td1(line1, line2, line3)
    if not result["valid"]:
        raise HTTPException(
            status_code=422,
            detail="La foto no se pudo leer con confianza (no coincide el dígito verificador) — intenta tomarla de nuevo.",
        )

    return {"id": result["id"], "first_name": result["first_name"], "last_name": result["last_name"]}
