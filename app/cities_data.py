"""Ciudades por país para el selector del formulario de evento.

Dataset real de GeoNames (cities15000: todas las ciudades del mundo con población >= 15,000,
~20 mil ciudades para los ~35 países que soporta este formulario) — no una lista escrita a mano.
Fuente: https://download.geonames.org/export/dump/ (dominio público / CC BY 4.0).
Generado una vez con un script offline (no se descarga en cada arranque); ver
`cities_by_country.json` en esta misma carpeta. Ordenadas por población descendente, así las
ciudades más grandes/relevantes aparecen primero en las sugerencias.

El campo de ciudad en el formulario siempre acepta texto libre también, para el caso raro de un
lugar con menos de 15,000 habitantes que no esté en este dataset.
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cities_by_country.json")
with open(_PATH, encoding="utf-8") as _f:
    COUNTRY_CITIES = json.load(_f)
