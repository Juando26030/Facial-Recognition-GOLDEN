"""Escribe las variables de entorno de un Job generador como archivo para `gcloud run jobs deploy --env-vars-file` (JSON, que es YAML válido).

    python3 deploy/loadtest/job_env.py <salida.json> CLAVE=valor CLAVE2=valor2 ...

Por qué un archivo y no `--set-env-vars "A=x,B=y"`: gcloud usa la COMA como separador de variables, así que un valor con comas (LOAD_ALLOWED_HOSTS es una lista de hosts
separada por comas) se partía en variables falsas («Bad syntax for dict arg»). En un archivo cada valor es una cadena JSON entera: las comas, «=» y espacios no molestan.
Es el mismo mecanismo que usa deploy/gcp/deploy.sh (`--env-vars-file`). `run_task.py` sigue leyendo LOAD_ALLOWED_HOSTS separado por comas (`.split(",")`)."""
import json
import sys


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    env = {}
    for pair in argv[1:]:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            print(f"Argumento inválido (se espera CLAVE=valor): {pair!r}", file=sys.stderr)
            return 2
        env[key] = value                                     # siempre cadena: gcloud exige valores de texto
    with open(argv[0], "w", encoding="utf8") as fh:
        json.dump(env, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
