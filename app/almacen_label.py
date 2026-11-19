"""Plantilla de la etiqueta QR del almacén (editable desde la ventana «Etiquetas», la comparten todos los que imprimen). Módulo puro: valida y completa lo guardado.
Se guarda como JSON en `app_settings` (clave `almacen_label_template`). La página del rollo mide SIEMPRE 62 mm de ancho (Brother QL-800); aquí solo se elige el alto y cómo se acomoda lo de adentro."""
import json
from typing import Optional

SETTING_KEY = "almacen_label_template"
QR_POS = ("left", "right", "top", "none")
ALIGN = ("left", "center")
DEFAULTS = {"height_mm": 29, "qr_pos": "left", "qr_mm": 0, "show_title": True, "show_code": True, "show_sub": True,
            "title_mm": 3.8, "code_mm": 3.6, "sub_mm": 2.8, "align": "left", "extra_text": "", "copies": 1}


def _num(v, lo, hi, default, integer=False):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    n = max(lo, min(hi, n))
    return int(round(n)) if integer else round(n, 1)


def clean(raw: Optional[dict]) -> dict:
    """Siempre devuelve una plantilla completa y dentro de límites (lo que no sirve vuelve al valor de fábrica)."""
    r = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    out["height_mm"] = _num(r.get("height_mm"), 15, 100, DEFAULTS["height_mm"], True)
    out["qr_pos"] = r.get("qr_pos") if r.get("qr_pos") in QR_POS else DEFAULTS["qr_pos"]
    out["qr_mm"] = _num(r.get("qr_mm"), 0, 60, 0, True)          # 0 = automático (alto − 5 mm)
    for k in ("show_title", "show_code", "show_sub"):
        out[k] = bool(r[k]) if k in r else DEFAULTS[k]
    out["title_mm"] = _num(r.get("title_mm"), 2, 9, DEFAULTS["title_mm"])
    out["code_mm"] = _num(r.get("code_mm"), 2, 9, DEFAULTS["code_mm"])
    out["sub_mm"] = _num(r.get("sub_mm"), 1.5, 7, DEFAULTS["sub_mm"])
    out["align"] = r.get("align") if r.get("align") in ALIGN else DEFAULTS["align"]
    out["extra_text"] = " ".join(str(r.get("extra_text") or "").split())[:60]
    out["copies"] = _num(r.get("copies"), 1, 10, 1, True)
    return out


def load(raw_json: Optional[str]) -> dict:
    try:
        return clean(json.loads(raw_json)) if raw_json else clean(None)
    except ValueError:
        return clean(None)
