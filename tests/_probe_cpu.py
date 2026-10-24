"""SONDA de CPU de la carga (no se recoge como prueba). Mide el tiempo de CPU del proceso (lo que costaría en 1 vCPU) y los puntos calientes de la carga masiva.
  PROBE_N=8000 python -m pytest -q -s tests/_probe_cpu.py"""
import cProfile
import io
import os
import pstats
import time

from tests._golden_load import xlsx_bytes
from tests.conftest import login
from tests.test_rendimiento import _rows

N = int(os.getenv("PROBE_N", "8000"))


def test_probe_cpu(client, factory, db):
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    data = xlsx_bytes(_rows(N))
    for label, profile in (("sin perfilador", False), ("con perfilador", True)):
        ev2 = factory.event("creado")
        c0, w0 = time.process_time(), time.perf_counter()
        pr = cProfile.Profile()
        if profile:
            pr.enable()
        r = client.post("/api/bulk_register", data={"event_id": str(ev2.id)}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})
        if profile:
            pr.disable()
        c1, w1 = time.process_time(), time.perf_counter()
        assert r.status_code == 200 and r.json()["count"] == N
        print(f"\n[CPU] {label}: filas={N} tiempo_real={w1 - w0:.2f}s cpu_proceso={c1 - c0:.2f}s ({(c1 - c0) / N * 1000:.2f} ms de CPU por fila)")
        if profile:
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(18)
            print("\n".join(l[:170] for l in s.getvalue().splitlines() if l.strip())[:5200])


def test_probe_steps(client, factory, db):
    """La carga POR PASOS como la ve el navegador: tiempo de cada petición, consultas y CPU. PROBE_RTT_MS simula el viaje a Neon por consulta."""
    from tests.test_rendimiento import SqlCount
    from sqlalchemy import event as sa_event
    from app.database import engine
    rtt = float(os.getenv("PROBE_RTT_MS", "0")) / 1000
    if rtt:
        sa_event.listen(engine, "before_cursor_execute", lambda *a, **k: time.sleep(rtt))
    factory.staff("coordinador", "coord1")
    login(client, "coord1")
    ev = None
    for label, reload in (("carga nueva", False), ("misma carga otra vez (personas ya existentes)", True)):
        ev = factory.event("creado") if not reload else ev
        data = xlsx_bytes(_rows(N))
        t0, c0 = time.perf_counter(), time.process_time()
        times, queries = [], []
        with SqlCount() as q:
            r = client.post("/api/bulk_register", data={"event_id": str(ev.id), "background": "true"}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})
        times.append(time.perf_counter() - t0); queries.append(q.n)
        st = r.json()
        while st["status"] == "running":
            t = time.perf_counter()
            with SqlCount() as q:
                st = client.post(f"/api/bulk_jobs/{r.json()['job_id']}/step").json()
            times.append(time.perf_counter() - t); queries.append(q.n)
        total = time.perf_counter() - t0
        print(f"\n[PASOS] {label}: filas={N} total={total:.2f}s cpu={time.process_time() - c0:.2f}s peticiones={len(times)} (la más lenta {max(times):.2f}s) consultas por petición={queries} estado={st['status']} count={st['result']['count']}")
