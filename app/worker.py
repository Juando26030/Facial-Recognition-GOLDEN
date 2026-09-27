"""Worker de la cola de trabajos como proceso aparte: `python -m app.worker` (o `--once` para vaciar la cola y salir).

Hoy el hilo del worker vive dentro del proceso web (JOBS_WORKER=on). Este módulo es la misma cola corriendo sola: en la VM sirve para no cargar a los
procesos web, y en Cloud Run será el Cloud Run Job / el destino de Cloud Tasks. Apagado ordenado: SIGTERM/SIGINT terminan el trabajo en curso y salen."""
import argparse
import logging
import signal
import threading

from app import jobs, obs
from app import reconcile  # noqa: F401 — registra el trabajo `payments_reconcile`
from app import formsvc  # noqa: F401 — registra el trabajo `form_feed`

log = logging.getLogger("golden.worker")


def main() -> None:
    obs.configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="ejecuta lo que esté vencido y sale")
    args = parser.parse_args()
    if args.once:
        log.info("trabajos ejecutados: %s", jobs.drain())
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    worker = jobs.Worker()
    worker.start()
    stop.wait()
    log.info("apagando worker")
    worker.stop()


if __name__ == "__main__":
    main()
