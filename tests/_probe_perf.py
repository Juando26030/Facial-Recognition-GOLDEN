"""SONDA de rendimiento (no es una prueba del conjunto: el guion bajo inicial evita que pytest la recoja). Correr a mano:
  python -m pytest -q -s tests/_probe_perf.py -k <nombre>
Mide, contra la base LOCAL de pruebas, la carga masiva del Excel y el reporte, con número de consultas SQL, tiempo y, opcionalmente, una latencia artificial por consulta (PROBE_RTT_MS) que imita el viaje a Neon."""
import cProfile
import io
import os
import pstats
import time
from datetime import datetime, timedelta

import pytest
from openpyxl import Workbook

from app.database import engine
from app.models import AccessLog, EventAttendee
from sqlalchemy import event as sa_event
from tests.conftest import login

RTT = float(os.getenv("PROBE_RTT_MS", "0")) / 1000.0
N = int(os.getenv("PROBE_N", "1000"))


class Counter:
    def __init__(self):
        self.n = 0
        self.sql_s = 0.0
        self.kinds = {}
        self._t = None

    def attach(self):
        @sa_event.listens_for(engine, "before_cursor_execute")
        def _b(conn, cur, stmt, params, ctx, many):
            self._t = time.perf_counter()
            if RTT:
                time.sleep(RTT)

        @sa_event.listens_for(engine, "after_cursor_execute")
        def _a(conn, cur, stmt, params, ctx, many):
            self.n += 1
            self.sql_s += time.perf_counter() - self._t
            k = stmt.strip().split()[0].upper() + " " + (stmt.split("FROM")[1].split()[0] if "FROM" in stmt else stmt.split()[2] if len(stmt.split()) > 2 else "")
            self.kinds[k] = self.kinds.get(k, 0) + 1
        self._b, self._a = _b, _a

    def detach(self):
        sa_event.remove(engine, "before_cursor_execute", self._b)
        sa_event.remove(engine, "after_cursor_execute", self._a)


def _xlsx(n, base=9900000000):
    wb = Workbook()
    ws = wb.active
    ws.append(["id", "nombres", "apellidos", "cargo", "entidad", "telefono", "correo", "tipo de asistente", "categoria", "Fecha nac. cliente"])
    for i in range(n):
        ws.append([str(base + i + 1), f"Nombre{i}", f"Apellido{i}", "Asistente", f"Empresa {i % 40}", f"300{1000000 + i}", f"p{i}@example.com", "Invitado", ["General", "Zona A", ""][i % 3], "10/03/1990"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _top(pr, n=14):
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(n)
    return "\n".join(l[:150] for l in s.getvalue().splitlines() if l.strip())[:3800]


def test_probe_load(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("creado")
    login(client, "coord1")
    data = _xlsx(N)
    c = Counter(); c.attach()
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", data, "application/octet-stream")})
    pr.disable()
    total = time.perf_counter() - t0
    c.detach()
    assert r.status_code == 200, r.text[:300]
    print(f"\n[CARGA] filas={N} total={total:.2f}s consultas={c.n} (en SQL={c.sql_s:.2f}s, rtt_artificial={RTT * 1000:.0f}ms) por_fila={c.n / N:.1f} consultas, {total / N * 1000:.1f} ms/fila; count={r.json()['count']} errores={len(r.json()['errors'])}")
    top = sorted(c.kinds.items(), key=lambda kv: -kv[1])[:8]
    print("[CARGA] consultas más repetidas:", top)
    print(_top(pr))


def test_probe_report(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", _xlsx(N), "application/octet-stream")})
    assert r.status_code == 200
    db.execute(__import__("sqlalchemy").text("UPDATE events SET roster_uploaded = true WHERE id = :i"), {"i": ev.id})
    base = datetime.utcnow() - timedelta(hours=3)
    ids = [a.user_id for a in db.query(EventAttendee).filter_by(event_id=ev.id)]
    for i, uid in enumerate(ids[: int(len(ids) * 0.9)]):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, record_type="Existente", registration_method="tradicional", timestamp=base + timedelta(seconds=i)))
    db.commit()
    c = Counter(); c.attach()
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    rep = client.get(f"/api/report?event_id={ev.id}")
    pr.disable()
    total = time.perf_counter() - t0
    c.detach()
    assert rep.status_code == 200, rep.text[:300]
    print(f"\n[REPORTE] personas={N} total={total:.2f}s consultas={c.n} (en SQL={c.sql_s:.2f}s, rtt_artificial={RTT * 1000:.0f}ms) bytes={len(rep.content)}")
    print("[REPORTE] consultas:", sorted(c.kinds.items(), key=lambda kv: -kv[1])[:8])
    print(_top(pr))


def test_probe_report_signature(client, factory, db, monkeypatch):
    """Hipótesis: un evento con un campo de FIRMA hace un `exists()` al almacenamiento por persona (en la nube, una petición HTTP a Cloud Storage cada una)."""
    from app.models import EventFieldConfig
    from app.storage import get_storage
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    ev.set_optional_labels({"opcional_1": "Firma del asistente"})
    db.add(EventFieldConfig(event_id=ev.id, field_key="opcional_1", label="Firma del asistente", field_type="signature"))
    db.commit()
    r = client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", _xlsx(N), "application/octet-stream")})
    assert r.status_code == 200
    st = get_storage()
    calls = {"n": 0}
    real = type(st).exists
    gcs_ms = float(os.getenv("PROBE_GCS_MS", "15")) / 1000

    def slow_exists(self, key):
        calls["n"] += 1
        time.sleep(gcs_ms)
        return real(self, key)
    monkeypatch.setattr(type(st), "exists", slow_exists)
    t0 = time.perf_counter()
    rep = client.get(f"/api/report?event_id={ev.id}")
    total = time.perf_counter() - t0
    assert rep.status_code == 200
    print(f"\n[REPORTE+FIRMA] personas={N} total={total:.1f}s llamadas_al_almacenamiento={calls['n']} (cada una simulada a {gcs_ms * 1000:.0f} ms)")


def test_probe_report_async(client, factory, db):
    """Reporte en segundo plano: lo que ve el navegador (cada petición por separado)."""
    factory.staff("coordinador", "coord1")
    ev = factory.event("en_proceso")
    login(client, "coord1")
    assert client.post("/api/bulk_register", data={"event_id": str(ev.id)}, files={"roster_file": ("p.xlsx", _xlsx(N), "application/octet-stream")}).status_code == 200
    base = datetime.utcnow() - timedelta(hours=3)
    for i, a in enumerate(list(db.query(EventAttendee).filter_by(event_id=ev.id))[: int(N * 0.9)]):
        db.add(AccessLog(tenant_id=ev.tenant_id, user_id=a.user_id, event_id=ev.id, record_type="Existente", registration_method="qr", timestamp=base + timedelta(seconds=i)))
    db.commit()
    c = Counter(); c.attach()
    t0 = time.perf_counter()
    st = client.post("/api/report/start", json={"event_id": ev.id}).json()
    t_start = time.perf_counter() - t0
    polls = []
    while st["status"] in ("queued", "running"):
        time.sleep(0.2)
        t = time.perf_counter()
        st = client.get(f"/api/report/status/{st['job_id']}").json()
        polls.append(time.perf_counter() - t)
    done = time.perf_counter() - t0
    t = time.perf_counter()
    dl = client.get(f"/api/report/download/{st['job_id']}")
    t_dl = time.perf_counter() - t
    c.detach()
    print(f"\n[REPORTE-ASYNC] personas={N} de punta a punta={done + t_dl:.2f}s | iniciar={t_start:.2f}s, estado(máx)={max(polls or [0]):.2f}s, descargar={t_dl:.2f}s | consultas={c.n} estado={st['status']} bytes={len(dl.content)}")
