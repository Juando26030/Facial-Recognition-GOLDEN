"""Genera static/data/geo.json (países y ciudades) desde scripts/geo_fuente/.

Uso:  python scripts/build_geo_data.py
Se edita la fuente (paises.txt, ciudades_*.txt, colombia.py), se corre esto y se hace commit de AMBOS.
Sin red: Colombia parte de app/cities_by_country.json (GeoNames, ya versionado) depurado en colombia.py.
"""
import json
import os
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUENTE = os.path.join(ROOT, "scripts", "geo_fuente")
SALIDA = os.path.join(ROOT, "static", "data", "geo.json")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from geo_fuente import colombia  # noqa: E402

VERSION = "2026-11-07"
FUENTE_TXT = "Elaborado a mano con conocimiento general (Colombia: GeoNames cities15000 depurado), noviembre 2026; revisar."


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def dedupe(items):
    visto, out = set(), []
    for x in items:
        x = x.strip()
        if x and norm(x) not in visto:
            visto.add(norm(x))
            out.append(x)
    return out


def main():
    paises = {}
    with open(os.path.join(FUENTE, "paises.txt"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                code, es, en = line.strip().split("|")
                paises[code] = {"code": code, "name": es, "en": en, "cities": []}
    for fn in sorted(os.listdir(FUENTE)):
        if fn.startswith("ciudades_") and fn.endswith(".txt"):
            with open(os.path.join(FUENTE, fn), encoding="utf-8") as f:
                for line in f:
                    if ":" in line:
                        code, rest = line.split(":", 1)
                        paises[code.strip()]["cities"] = dedupe(rest.split(";"))
    with open(os.path.join(ROOT, "app", "cities_by_country.json"), encoding="utf-8") as f:
        base = [c for c in json.load(f)["Colombia"] if c not in colombia.QUITAR]
    paises["CO"]["cities"] = dedupe(base + colombia.AGREGAR)
    lista = sorted(paises.values(), key=lambda p: norm(p["name"]))
    data = {"version": VERSION, "source": FUENTE_TXT, "countries": lista}
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(len(lista), "países;", sum(len(p["cities"]) for p in lista), "ciudades")
    print("sin ciudades:", [p["code"] for p in lista if not p["cities"]])


if __name__ == "__main__":
    main()
