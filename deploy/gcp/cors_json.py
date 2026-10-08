"""Regla de CORS del bucket de la app: la plantilla deploy/gcs-app-cors.json con los orígenes de este entorno (uno por argumento). Imprime el JSON listo para `--cors-file`."""
import json
import os
import sys

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "gcs-app-cors.json")


def build(origins):
    rules = json.load(open(TEMPLATE, encoding="utf-8"))
    rules[0]["origin"] = sorted({o.rstrip("/") for o in origins if o.strip()})
    return rules


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1:])))
