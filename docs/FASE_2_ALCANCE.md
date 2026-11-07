# Fase 2: alcance

## Datos de países y ciudades

**Qué es.** Lista fija dentro de la plataforma (sin servicios externos) para los campos «País» y «Ciudad» de las plantillas de evento. Decisión de Juan David: País = lista de todos los países que se puede filtrar escribiendo; Ciudad = por defecto las ciudades del país elegido, y si no está, texto abierto.

**Dónde está.**
- `static/data/geo.json`: 202 países (los 195 reconocidos + Kosovo, Taiwán, Puerto Rico, Hong Kong, Macao, Aruba, Curazao). Cada uno con código ISO alfa-2, nombre en español, nombre en inglés (para buscar) y ciudades ordenadas por relevancia. Colombia trae más de 300 municipios (capitales departamentales y municipios de más de ~15.000 habitantes, más los de los cupos: Bogotá, Girardot, Montelíbano, Boyacá...). El resto: capital y ciudades principales.
- `static/js/gw-geo.js`: lógica pura (búsqueda sin acentos ni mayúsculas, orden: empieza igual, luego palabra, luego contiene; límite 50). `GWGeo.searchCountries(q)`, `GWGeo.citiesOf(code)`, `GWGeo.searchCities(code, q)` devuelven `[{value,label}]` (país: value = código). Se carga con `GWGeo.load("{{ url_for('static', path='data/geo.json') }}")`; si la ciudad no está (`GWGeo.isKnownCity`), el campo queda como texto abierto.
- `app/geo.py`: la misma normalización y consultas para validar en el servidor.

**Por qué JSON estático y no endpoint.** Son datos públicos sin información personal; `url_for('static')` agrega `?v=` y el navegador/CDN lo cachea (~36 KB). Un endpoint exigiría sesión, base y respuesta por país sin ganar nada.

**Fuente.** Elaborado a mano con conocimiento general, noviembre 2026; revisar. Colombia parte de GeoNames (`app/cities_by_country.json`, ya en el repo) depurado a mano (se quitan localidades como «Kennedy», se corrigen nombres).

**Cómo actualizar.**
1. Editar la fuente en `scripts/geo_fuente/`: `paises.txt` (`CÓDIGO|español|inglés`), `ciudades_*.txt` (`CÓDIGO: ciudad; ciudad; ...`, las más importantes primero) y `colombia.py` (`QUITAR` / `AGREGAR`).
2. `python scripts/build_geo_data.py` (regenera `static/data/geo.json`; no necesita red).
3. `python -m pytest -q tests/test_geo_data.py` y `node tests/js/gw_geo_check.js`.
4. Commit de la fuente y del JSON juntos.
