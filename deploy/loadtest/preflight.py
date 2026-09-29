"""Comprobación previa de `run_phase4.sh run`: lee la descripción JSON de un servicio de Cloud Run (`gcloud run services describe … --format=json`, por la entrada estándar) y
falla si NO tiene lo que la prueba necesita. Un despliegue de CI (`--env-vars-file` reemplaza TODAS las variables y `--max-instances` vuelve al valor de deploy.sh) borra lo que
pusieron `limits-up` y `scale-up`; sin esta comprobación la prueba correría sin ellos y mediría otra cosa.

    gcloud run services describe golden-publico-staging --region R --format=json | python3 deploy/loadtest/preflight.py golden-publico-staging 6 200
    argumentos: <servicio> <máximo de instancias esperado> [<PUBLIC_LIMIT_FACTOR esperado>]

Entiende las dos formas de la API (v1: annotations/env de la plantilla; v2: template.scaling/containers). Imprime el problema y el comando que lo arregla; código 1 si hay alguno."""
import json
import sys


def _template(svc: dict) -> tuple:
    """(máximo de instancias como texto o None, {variable: valor})."""
    v1 = (svc.get("spec") or {}).get("template") or {}
    v2 = svc.get("template") or {}
    max_scale = ((v1.get("metadata") or {}).get("annotations") or {}).get("autoscaling.knative.dev/maxScale")
    if max_scale is None:
        max_scale = (v2.get("scaling") or {}).get("maxInstanceCount")
    containers = ((v1.get("spec") or {}).get("containers")) or v2.get("containers") or [{}]
    env = {e.get("name"): e.get("value") for e in (containers[0].get("env") or [])}
    return (None if max_scale is None else str(max_scale)), env


def problems(svc: dict, name: str, expect_max: int, expect_factor=None) -> list:
    max_scale, env = _template(svc)
    out = []
    if max_scale != str(expect_max):
        out.append(f"{name}: máximo de instancias = {max_scale or 'sin definir'}, esperado {expect_max}. Un despliegue lo restablece a 10: corre `run_phase4.sh scale-up` "
                   f"(si ya hay originales guardados, primero `scale-down`).")
    if expect_factor is not None and env.get("PUBLIC_LIMIT_FACTOR") != str(expect_factor):
        out.append(f"{name}: PUBLIC_LIMIT_FACTOR = {env.get('PUBLIC_LIMIT_FACTOR', 'sin definir')}, esperado {expect_factor}. Un despliegue (--env-vars-file) borra las variables puestas a mano: "
                   f"corre `run_phase4.sh limits-up`.")
    return out


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    name, expect_max = argv[0], int(argv[1])
    expect_factor = argv[2] if len(argv) > 2 else None
    try:
        svc = json.load(sys.stdin)
    except ValueError:
        print(f"PREFLIGHT: no pude leer la descripción de {name} (¿existe el servicio y tienes permiso?).", file=sys.stderr)
        return 1
    found = problems(svc, name, expect_max, expect_factor)
    for line in found:
        print("PREFLIGHT FALLÓ — " + line, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
