"""Almacén (bodega) — Pieza 1: catálogo ampliado, unidades con serial y códigos QR (rama almacen/p1-catalogo, plan: claude/58_PLAN_ALMACEN).

Se EXTIENDE el catálogo de inventario que ya existe (app/inventory.py, `inventory_products`): no hay un catálogo paralelo. Cada producto gana tres datos:
  · `tracking`: cómo se controla en bodega.
        serial    → cada equipo es una UNIDAD con su propio QR (portátil, lector, tablet, monitor…)
        modelo    → un QR por modelo; se escanea sumando cantidad (p. ej. cada modelo de impresora)
        cantidad  → un QR por tipo, con la cantidad que se escribe al escanear (cables, cargadores, papelería…)
  · `checklist_row`: a cuál fila del checklist GEYL (formato Excel por evento) suma ese producto.
  · `is_consumable`: se gasta y no vuelve (cinta, papel, tóner); el almacén lo repone y lo cuenta a mano.

Módulo puro (sin base de datos ni FastAPI): lo usan app/routers/almacen.py y las pruebas. Lanza AlmacenError con mensajes en español.
Interruptor `ALMACEN_ENABLED` (por defecto 0): con 0 no hay rutas ni pantalla de almacén (staging 1 y producción 0 en deploy/gcp/config.sh).
"""
import os
import re
import secrets
from typing import List, Optional

TRACKING = ("serial", "modelo", "cantidad")
TRACKING_INFO = {
    "serial": {"label": "Con serial (un QR por equipo)", "hint": "Portátiles, lectores, tablets, monitores: cada equipo tiene su propio número y QR."},
    "modelo": {"label": "Por modelo (un QR por modelo)", "hint": "Impresoras: un QR por modelo; al escanear se suma una unidad."},
    "cantidad": {"label": "Por cantidad (un QR por tipo)", "hint": "Cables, cargadores, papelería: un QR por tipo y la cantidad se escribe al escanear."},
}

# Estados de una unidad. «novedad» (Pieza 3) bloquea la asignación a un evento hasta que almacén la deje «disponible».
UNIT_STATUS = ("disponible", "en_evento", "novedad")
UNIT_STATUS_LABEL = {"disponible": "Disponible", "en_evento": "En un evento", "novedad": "En novedad"}

MAX_UNITS_PER_BATCH = 100
MAX_LABELS_PER_PRINT = 200
MAX_SERIAL = 80

# Códigos QR: SOLO letras mayúsculas y números, sin guiones ni símbolos (el lector USB escribe como teclado y los símbolos cambian según la distribución),
# y sin caracteres que se confunden (0/O, 1/I/L).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_PREFIX = "GW"
CODE_RANDOM_LEN = 6
_SCAN_RE = re.compile(r"^[A-Z0-9]{4,32}$")
_BAD = re.compile(r"[<>\x00-\x1f\x7f]")


class AlmacenError(ValueError):
    pass


def almacen_enabled() -> bool:
    return os.getenv("ALMACEN_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on", "si", "sí")


# ---------------------------------------------------------------- filas del checklist GEYL (Checklist_GEYL.xls, hoja «Hoja1»)
# (clave, texto tal cual el formato, sección, fila del Excel, tipo). tipo «inv» = suma inventario; «manual» = fila de verificación (casilla y observación, no descuenta nada).
_ROWS = [
    ("teclados", "Teclados", "hardware", 9, "inv"),
    ("mouse", "Mouse", "hardware", 10, "inv"),
    ("monitores_semaforos", "Monitores - Semaforos", "hardware", 11, "inv"),
    ("modulos_touch", "Módulos Touch", "hardware", 12, "inv"),
    ("tablets_ipads", "Tablets - Ipads", "hardware", 13, "inv"),
    ("portatiles", "PORTATILES", "hardware", 14, "inv"),
    ("cargador_portatil", "CARGADOR de portátil", "hardware", 15, "inv"),
    ("lectores", "LECTORES", "hardware", 16, "inv"),
    ("plato_poe", "PLATO Y POE", "hardware", 17, "inv"),
    ("router_cargador", "ROUTER Y CARGADOR", "hardware", 18, "inv"),
    ("cables_red_utp", "Cables de red UTP punto a punto", "hardware", 19, "inv"),
    ("impresora_hp_p1102w", "IMPRESORA HP LASSER JET P1102 W", "hardware", 20, "inv"),
    ("cable_usb_hp1100", "Cable USB impresoras HP1100", "hardware", 21, "inv"),
    ("cable_poder_hp1100", "Cable de poder Impresoras HP1100", "hardware", 22, "inv"),
    ("impresora_termica", "IMPRESORA TERMICA", "hardware", 23, "inv"),
    ("cable_usb_termica", "Cable USB impresoras Térmica", "hardware", 24, "inv"),
    ("cable_poder_termica", "Cable de poder Impresoras Térmica", "hardware", 25, "inv"),
    ("impresoras_inyeccion", "Impresoras de inyección de tinta con cable USB y Poder", "hardware", 26, "inv"),
    ("extension_grueso", "Cable extensión GRUESO", "hardware", 27, "inv"),
    ("extension_mediano", "Cable extensión MEDIANO", "hardware", 28, "inv"),
    ("pulpos", "Pulpos", "hardware", 29, "inv"),
    ("multitomas", "Multitomas", "hardware", 30, "inv"),
    ("toner_rollo", "Tonner o Rollo de repuesto", "hardware", 31, "inv"),
    ("radios", "RADIOS. Walkie Talkie - y cargador", "hardware", 32, "inv"),
    ("pano_limpieza", "Paño para limpiar equipos - spray con Sanpic", "hardware", 33, "inv"),
    ("cinta_doble_faz", "Cinta doble faz", "papeleria", 35, "inv"),
    ("cinta_transparente", "Cinta transparente", "papeleria", 36, "inv"),
    ("cinta_gaffer", "Cinta enmascarar o Gaffer", "papeleria", 37, "inv"),
    ("tijeras_bisturi", "Tijeras /Bisturí", "papeleria", 38, "inv"),
    ("memoria_usb", "Memoria USB", "papeleria", 39, "inv"),
    ("stickers", "Stickers", "papeleria", 40, "inv"),
    ("escarapelas_blanco", "Escarapelas en blanco de soporte", "papeleria", 41, "inv"),
    ("escarapelas", "Escarapelas", "papeleria", 42, "inv"),
    ("certificados", "Certificados", "papeleria", 43, "inv"),
    ("cordones_fundas", "Cordones-Fundas", "papeleria", 44, "inv"),
    ("cintas", "Cintas", "papeleria", 45, "inv"),
    ("listado_personal", "Listado personal contratado", "varios", 47, "manual"),
    ("lista_telefonos", "Lista teléfonos proveedores de alquiler de equipos, papelería", "varios", 48, "manual"),
    ("listado_equipos_seriales", "Listado con equipos y seriales a ingresar", "varios", 49, "manual"),
    ("panoletas", "PAÑOLETAS cantidad y COLOR", "varios", 50, "inv"),
    ("corbatas", "CORBATAS cantidad y COLOR", "varios", 51, "inv"),
    ("plan_b", "Plan B equipos que fallen o si se necesita otro", "varios", 52, "manual"),
    ("encargado_acarreo", "Encargado acarreo ingreso y retiro equipos teléfono", "varios", 53, "manual"),
]
SECTIONS = {"hardware": "HARDWARE NUMERADOS", "papeleria": "PAPELERIA", "varios": "VARIOS"}
CHECKLIST_ROWS = [{"key": k, "label": lb, "section": s, "section_label": SECTIONS[s], "excel_row": r, "kind": kd} for k, lb, s, r, kd in _ROWS]
_ROW_BY_KEY = {r["key"]: r for r in CHECKLIST_ROWS}


def inventory_row_keys() -> List[str]:
    """Claves de las filas que SÍ suman inventario (las manuales no)."""
    return [r["key"] for r in CHECKLIST_ROWS if r["kind"] == "inv"]


def clean_tracking(value) -> str:
    v = str(value or "").strip().lower()
    if v not in TRACKING:
        raise AlmacenError("Elige cómo se controla el elemento: con serial, por modelo o por cantidad.")
    return v


def clean_checklist_row(value) -> Optional[str]:
    """Vacío = sin fila (no sale en el checklist). Solo las filas de inventario se pueden elegir."""
    v = str(value or "").strip()
    if not v:
        return None
    row = _ROW_BY_KEY.get(v)
    if row is None:
        raise AlmacenError("Esa fila del checklist no existe.")
    if row["kind"] != "inv":
        raise AlmacenError(f"La fila «{row['label']}» es de verificación manual: no suma inventario.")
    return v


def clean_serial(value) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if len(v) > MAX_SERIAL:
        raise AlmacenError(f"El serial no puede pasar de {MAX_SERIAL} caracteres.")
    if _BAD.search(v):
        raise AlmacenError("El serial trae caracteres no permitidos.")
    return v


def clean_count(value, maximum: int = MAX_UNITS_PER_BATCH) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise AlmacenError("La cantidad debe ser un número entero.")
    if n < 1 or n > maximum:
        raise AlmacenError(f"La cantidad debe estar entre 1 y {maximum}.")
    return n


def clean_ids(raw, what: str, maximum: int = MAX_LABELS_PER_PRINT) -> List[int]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)):
        raise AlmacenError(f"{what}: formato no válido.")
    out: List[int] = []
    for x in raw:
        try:
            n = int(x)
        except (TypeError, ValueError):
            raise AlmacenError(f"{what}: formato no válido.")
        if n not in out:
            out.append(n)
    if len(out) > maximum:
        raise AlmacenError(f"Se pueden imprimir hasta {maximum} etiquetas a la vez.")
    return out


# ---------------------------------------------------------------- códigos QR
def new_code() -> str:
    """Código para un QR: «GW» + 6 caracteres sin ambigüedad (≈ 1.000 millones de combinaciones). La unicidad la confirma la base (índice único) y el llamador reintenta."""
    return CODE_PREFIX + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_RANDOM_LEN))


def normalize_scan(text) -> Optional[str]:
    """Lo que escribe el lector USB (como teclado) → código. Quita espacios y saltos, pasa a mayúscula; None si no puede ser un código nuestro."""
    v = re.sub(r"\s+", "", str(text or "")).upper()
    return v if _SCAN_RE.match(v) else None


def unit_title(product_name: str, number: int) -> str:
    return f"{product_name} #{number}"
