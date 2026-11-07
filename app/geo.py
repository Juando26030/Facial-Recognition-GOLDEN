"""Países y ciudades de la plataforma (lista fija, sin servicios externos).

Datos en static/data/geo.json (los consume el navegador con url_for('static', ...); ver
docs/FASE_2_ALCANCE.md, «Datos de países y ciudades»). Este módulo sirve para validar en el servidor
y comparte la normalización de búsqueda con static/js/gw-geo.js (mismas reglas: sin acentos, minúsculas).
"""
import json
import os
import unicodedata
from functools import lru_cache

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "data", "geo.json")


def normalize(text):
    """Minúsculas, sin acentos/diacríticos y espacios colapsados («Bogotá » -> «bogota»)."""
    s = unicodedata.normalize("NFD", str(text or "").lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


@lru_cache(maxsize=1)
def load():
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def countries():
    return load()["countries"]


def country_by_code(code):
    code = str(code or "").upper()
    return next((c for c in countries() if c["code"] == code), None)


def find_country(text):
    """País por código o por nombre (español o inglés) sin importar acentos; None si no existe."""
    n = normalize(text)
    for c in countries():
        if n in (normalize(c["code"]), normalize(c["name"]), normalize(c["en"])):
            return c
    return None


def is_known_city(code, city):
    c = country_by_code(code)
    return bool(c) and normalize(city) in {normalize(x) for x in c["cities"]}
