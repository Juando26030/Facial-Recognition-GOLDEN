"""Integridad de los datos de países y ciudades (static/data/geo.json, app/geo.py)."""
import re

from app import geo

# Ciudades de los cupos de producción conocidos (evento 11 y otros): deben estar en Colombia.
CIUDADES_CUPOS = ["Bogotá", "Girardot", "Montelíbano", "Boyacá"]


def test_paises_completos_y_codigos_unicos():
    cs = geo.countries()
    assert len(cs) >= 195
    codes = [c["code"] for c in cs]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"[A-Z]{2}", x) for x in codes)
    nombres = [geo.normalize(c["name"]) for c in cs]
    assert len(nombres) == len(set(nombres))
    assert all(c["name"] and c["en"] for c in cs)


def test_sin_duplicados_ni_vacios_en_ciudades():
    for c in geo.countries():
        assert c["cities"], c["code"]
        n = [geo.normalize(x) for x in c["cities"]]
        assert len(n) == len(set(n)), c["code"]
        assert all(x.strip() == x and x for x in c["cities"]), c["code"]


def test_colombia_completa():
    co = geo.country_by_code("co")
    assert co and co["name"] == "Colombia" and len(co["cities"]) >= 250
    caps = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena", "Cúcuta", "Bucaramanga", "Pereira", "Santa Marta", "Ibagué",
            "Pasto", "Manizales", "Neiva", "Villavicencio", "Armenia", "Valledupar", "Montería", "Sincelejo", "Popayán", "Tunja",
            "Riohacha", "Florencia", "Yopal", "Quibdó", "Arauca", "Mocoa", "San Andrés", "Leticia", "Inírida", "Mitú",
            "San José del Guaviare", "Puerto Carreño"]
    for ciudad in caps:
        assert geo.is_known_city("CO", ciudad), ciudad
    assert not geo.is_known_city("CO", "Kennedy") and not geo.is_known_city("CO", "Girardot City")


def test_ciudades_de_cupos_en_colombia():
    for ciudad in CIUDADES_CUPOS:
        assert geo.is_known_city("CO", ciudad), ciudad


def test_normalizacion():
    assert geo.normalize("  BOGOTÁ ") == "bogota"
    assert geo.normalize("Düsseldorf") == "dusseldorf"
    assert geo.normalize(None) == ""
    assert geo.is_known_city("co", "montelibano")
    assert geo.find_country("peru")["code"] == "PE" and geo.find_country("Germany")["code"] == "DE"
    assert geo.find_country("inexistente") is None


def test_capitales_de_otros_paises():
    for code, ciudad in [("MX", "Ciudad de México"), ("ES", "Madrid"), ("US", "Washington D. C."), ("AR", "Buenos Aires"),
                         ("BR", "Brasilia"), ("PE", "Lima"), ("EC", "Quito"), ("VE", "Caracas"), ("FR", "París"), ("JP", "Tokio")]:
        assert geo.is_known_city(code, ciudad), (code, ciudad)
