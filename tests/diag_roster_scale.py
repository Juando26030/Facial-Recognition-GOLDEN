"""DIAGNÓSTICO de escala (no es una prueba de CI: el nombre no empieza por test_). Mide con un evento de N personas (por defecto 8.000 y 16.000) el roster local y el directorio en vivo:
tiempo del servidor, tamaño del JSON y gzip, filas devueltas y el total declarado, y si algún límite recorta en silencio.
Correr:  python -m pytest tests/diag_roster_scale.py -s -p no:cacheprovider        (SCALE_SIZES=8000,16000 para cambiar los tamaños)"""
import gzip
import json
import os
import time

import pytest

from app.models import EventAttendee, User
from tests.conftest import login

SIZES = [int(x) for x in os.getenv("SCALE_SIZES", "8000,16000").split(",")]


@pytest.mark.parametrize("n", SIZES)
def test_scale(client, factory, db, n):
    factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso")
    factory.authorize(ev, factory.staff("coordinador", "coord2"))
    db.bulk_insert_mappings(User, [{"id": str(10_000_000 + i), "tenant_id": ev.tenant_id, "first_name": f"Nombre{i}", "last_name": f"Apellido{i % 997}"} for i in range(n)])
    db.bulk_insert_mappings(EventAttendee, [{"event_id": ev.id, "user_id": str(10_000_000 + i), "tenant_id": ev.tenant_id, "categories": json.dumps(["VIP"] if i % 10 == 0 else [])} for i in range(n)])
    db.commit()
    login(client, "coord2")

    t = time.perf_counter()
    r = client.get(f"/api/events/{ev.id}/local-roster")
    dt = time.perf_counter() - t
    body = r.content
    data = r.json()
    print(f"\n[N={n}] local-roster: HTTP {r.status_code} · {dt * 1000:.0f} ms · {len(body) / 1024:.0f} KB sin comprimir · {len(gzip.compress(body)) / 1024:.0f} KB gzip · count={data['count']} · filas={len(data['people'])}")
    assert data["count"] == n == len(data["people"]), "el roster local NO recorta"

    t = time.perf_counter()
    r2 = client.get(f"/api/events/{ev.id}/local-roster", headers={"If-None-Match": r.headers["etag"]})
    print(f"[N={n}] local-roster con If-None-Match: HTTP {r2.status_code} · {(time.perf_counter() - t) * 1000:.0f} ms")

    got, total, page, t = 0, None, 1000, time.perf_counter()
    for off in range(0, n, page):
        rr = client.get(f"/api/users?event_id={ev.id}&limit={page}&offset={off}")
        total = int(rr.headers["X-Total-Count"]); got += len(rr.json())
    print(f"[N={n}] directorio en vivo por páginas de {page}: {got} filas de total={total} en {(time.perf_counter() - t) * 1000:.0f} ms ({n // page} páginas)")
    assert got == total == n, "el directorio en vivo permite llegar a todas"

    rr = client.get(f"/api/users?event_id={ev.id}")
    print(f"[N={n}] directorio en vivo SIN limit: HTTP {rr.status_code} · {len(rr.json())} filas · {len(rr.content) / 1024:.0f} KB")
