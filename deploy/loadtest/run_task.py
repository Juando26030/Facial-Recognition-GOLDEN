"""Una tarea de un Cloud Run Job = un generador de carga (Locust en el mismo proceso) contra STAGING. Fase 4 (docs/15, «Prueba de carga distribuida»).

Variables (las pone `deploy/loadtest/run_phase4.sh` con `--update-env-vars`; los totales se reparten entre las N tareas del Job):
  LOAD_SCENARIO   forms | cedula | face
  LOAD_HOST       https://…  OBLIGATORIO y debe contener «staging» (se niega a apuntar a cualquier otra cosa; nunca producción)
  LOAD_USERS      usuarios virtuales en TOTAL (forms: 10000 → una apertura cada uno; cedula: 200; face: p. ej. 60)
  LOAD_RATE       usuarios nuevos por segundo en TOTAL (forms: ~170 → 10.000 aperturas en ~60 s)
  LOAD_DURATION   segundos máximos (forms: 180; cedula: 1800; face: 300)
  LOAD_EVENT_ID, LOAD_FORM_SLUG, LOAD_PEOPLE, OPS_TOKEN   ver tests/load/locustfile.py (`scripts.seed_load_staging` los deja listos)
Imprime UNA línea `LOADGEN_RESULT {json}` con, por tipo de petición, cuántas hubo/fallaron y el histograma de tiempos (para unir las N tareas EXACTAMENTE con
scripts/loadgen_report.py) y los motivos de fallo. Sin datos personales: las cédulas/correos de la prueba son sintéticos y no se imprimen."""
import json
import math
import os
import sys
import time

import gevent
import locust  # importar locust primero: parchea gevent
from locust.env import Environment

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "load"), os.path.dirname(HERE)]      # en la imagen: /app/load (locustfile) y /app (scripts/load_cfg.py)

CLASSES = {"forms": "FormBurst", "cedula": "CedulaScanner", "face": "FaceScanner"}


def watch_generator(lags: list) -> None:
    """Mide la SATURACIÓN DEL PROPIO GENERADOR: cuánto se retrasa un `sleep(0.1)` (si el proceso no da abasto, los usuarios virtuales esperan turno y la latencia medida
    incluye esa espera, no solo la del servidor). Se guarda en LOADGEN_RESULT["generator"] y el informe la muestra."""
    while True:
        t = time.perf_counter()
        gevent.sleep(0.1)
        lags.append((time.perf_counter() - t - 0.1) * 1000)


def make_env(user_class, host):
    """events=locust.events: los oyentes del locustfile (`@events.request`, «[fuera de la app]», y `@events.quitting`) están en los eventos GLOBALES; un Environment sin este
    argumento crea los suyos y esos oyentes nunca se ejecutan (así se perdió la línea «[fuera de la app]» en la 3.ª corrida)."""
    return Environment(user_classes=[user_class], host=host, events=locust.events)


def main() -> int:
    scenario, host = os.environ["LOAD_SCENARIO"], os.environ["LOAD_HOST"].rstrip("/")
    if scenario not in CLASSES:
        sys.exit(f"LOAD_SCENARIO debe ser uno de {list(CLASSES)}")
    from scripts.load_cfg import check_host              # doble candado (ver load_cfg.check_host): host de staging Y, si viene LOAD_ALLOWED_HOSTS, uno de los EXACTOS de staging
    problem = check_host(host, os.getenv("LOAD_ALLOWED_HOSTS", "").split(","))
    if problem:
        sys.exit(f"Por seguridad no se genera carga contra este destino: {problem}")
    if not os.getenv("LOAD_ALLOWED_HOSTS"):
        sys.exit("Falta LOAD_ALLOWED_HOSTS (la pone deploy/loadtest/run_phase4.sh): sin la lista exacta de staging no se genera carga.")
    from scripts.load_cfg import submit_ratio
    submit_ratio()                                       # valida LOAD_SUBMIT_RATIO ANTES de generar carga (un valor inválido detiene la tarea)
    index, count = int(os.getenv("CLOUD_RUN_TASK_INDEX", "0")), int(os.getenv("CLOUD_RUN_TASK_COUNT", "1"))
    total_users, total_rate, duration = int(os.environ["LOAD_USERS"]), float(os.getenv("LOAD_RATE", "50")), int(os.getenv("LOAD_DURATION", "300"))
    users = total_users // count + (1 if index < total_users % count else 0)
    rate = max(1.0, total_rate / count)
    import locustfile
    env = make_env(getattr(locustfile, CLASSES[scenario]), host)
    runner = env.create_local_runner()
    lags: list = []
    gevent.spawn(watch_generator, lags)
    cpu0 = sum(os.times()[:2])
    started = time.time()
    runner.start(users, spawn_rate=rate)
    if scenario == "forms":                                   # cada usuario hace su parte y termina: se espera a que no quede ninguno
        gevent.sleep(2)
        while locustfile.DONE["users"] < users and time.time() - started < duration:          # usuarios que YA terminaron (no user_count: ver locustfile.FormBurst)
            gevent.sleep(1)
    else:
        gevent.sleep(duration)
    runner.quit()
    if scenario == "forms":                    # usuarios que NO terminaron cuando se acabó LOAD_DURATION (siguen reintentando): que no desaparezcan del informe
        for _ in range(users - locustfile.DONE["users"]):
            locust.events.request.fire(request_type="USER", name="[usuario] no terminó (cortado al agotarse LOAD_DURATION)", response_time=duration * 1000, response_length=0,
                                       exception=Exception("no terminó"), context={})
    entries = []
    for (name, method), e in env.stats.entries.items():
        entries.append({"name": name, "method": method, "requests": e.num_requests, "failures": e.num_failures, "max_ms": e.max_response_time,
                        "total_ms": e.total_response_time, "histogram": {str(k): v for k, v in e.response_times.items()}})
    errors = {f"{err.method} {err.name}: {err.error}"[:200]: err.occurrences for err in env.stats.errors.values()}
    wall = max(time.time() - started, 0.001)
    lags.sort()
    generator = {"cpu_pct": round(100 * (sum(os.times()[:2]) - cpu0) / wall), "lag_p95_ms": round(lags[int(len(lags) * .95)]) if lags else 0, "lag_max_ms": round(lags[-1]) if lags else 0}
    print("LOADGEN_RESULT " + json.dumps({"scenario": scenario, "task": index, "tasks": count, "users": users, "seconds": round(time.time() - started, 1),
                                          "entries": entries, "errors": errors, "generator": generator}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
