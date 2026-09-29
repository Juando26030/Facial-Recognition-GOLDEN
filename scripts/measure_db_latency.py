"""Mide la latencia app → Postgres (Neon) DESDE DONDE SE CORRE (pensado para un Cloud Run Job en la región candidata; sesión 3, D.2).

    python -m scripts.measure_db_latency [--n 200] [--rest-of-args]          # usa DATABASE_URL (y DIRECT_DATABASE_URL si existe)

Qué separa (todo en milisegundos, con mediana/p95/mín.), para saber DÓNDE se va el tiempo de `/ready` (43-46 ms medidos en staging, más de los ~10-15 ms
esperados entre us-east1 y Neon us-east-1):
  * conexión nueva (TCP + TLS + autenticación): lo que paga una petición si el pool está vacío o la conexión murió;
  * `SELECT 1` con la conexión ya abierta = UNA ida y vuelta (RTT) de la aplicación a la base, sin más;
  * `SELECT 1` × 2 seguidos = lo que cuesta `pool_pre_ping=True` + la consulta (cada préstamo de conexión del pool hace un ping antes de usarla);
  * lo mismo por el motor de la aplicación (`app.database.engine`), o sea EXACTAMENTE lo que mide `/ready` (`ops._db_probe`);
  * una transacción de 3 sentencias con commit (aprox. lo que hace un envío de formulario con el cupo en UNA sentencia: `form_reserve_slot`, INSERT, COMMIT).
Sin datos personales y sin tocar tablas: solo `SELECT 1` y `pg_sleep(0)`.
Imprime una línea `LATENCY_RESULT {json}` fácil de recoger con `gcloud logging read`, y una tabla legible."""
import argparse
import json
import os
import statistics
import time
import urllib.request


def region_label() -> str:
    """Región donde corre (servidor de metadatos de Google) para etiquetar el resultado; «desconocida» fuera de Cloud Run."""
    try:
        req = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/region", headers={"Metadata-Flavor": "Google"})
        return urllib.request.urlopen(req, timeout=2).read().decode().rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001
        return "desconocida"


def stats(values):
    v = sorted(values)
    return {"n": len(v), "min": round(v[0], 2), "p50": round(statistics.median(v), 2), "p95": round(v[max(0, int(len(v) * 0.95) - 1)], 2), "max": round(v[-1], 2)}


def timed(fn, n):
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def measure(url: str, n: int) -> dict:
    import psycopg2
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    sa_url = make_url(url)
    url = sa_url.set(drivername="postgresql").render_as_string(hide_password=False)          # libpq no entiende «+psycopg2»
    res = {}
    cold = []
    for _ in range(min(n, 8)):
        t0 = time.perf_counter()
        c = psycopg2.connect(url, connect_timeout=15)
        cold.append((time.perf_counter() - t0) * 1000)
        c.close()
    res["connect_new"] = stats(cold)
    conn = psycopg2.connect(url, connect_timeout=15)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1")                                   # calienta: la primera consulta de una conexión trae trabajo extra
    res["select1_warm_1rtt"] = stats(timed(lambda: cur.execute("SELECT 1"), n))
    res["select1_x2_like_preping"] = stats(timed(lambda: (cur.execute("SELECT 1"), cur.execute("SELECT 1")), n))

    def tx():
        conn.autocommit = False
        cur.execute("SELECT pg_sleep(0)")
        cur.execute("SELECT 1")
        cur.execute("SELECT 2")
        conn.commit()
        conn.autocommit = True

    res["tx_3_statements_commit"] = stats(timed(tx, max(20, n // 4)))
    conn.close()
    engine = create_engine(sa_url.set(drivername="postgresql+psycopg2"), pool_size=2, pool_pre_ping=True)   # el mismo pre_ping que app/database.py

    def like_ready():
        with engine.connect() as c:                            # préstamo del pool (pre_ping) + SELECT 1
            c.execute(text("SELECT 1"))

    like_ready()
    res["engine_checkout_select1_like_ready"] = stats(timed(like_ready, n))
    engine.dispose()
    return res


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()                                          # local: toma DATABASE_URL del .env; en Cloud Run ya vienen en el entorno
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    out = {"region": region_label(), "n": args.n, "results": {}}
    for label, var in (("pooler", "DATABASE_URL"), ("direct", "DIRECT_DATABASE_URL")):
        url = os.getenv(var)
        if not url:
            continue
        if label == "direct" and url == os.getenv("DATABASE_URL"):
            continue
        out["results"][label] = measure(url, args.n)
    print(f"Región de origen: {out['region']}  ·  n={args.n}\n")
    for label, r in out["results"].items():
        print(f"[{label}]")
        print("| medida | mín | p50 | p95 | máx |\n|---|---:|---:|---:|---:|")
        for k, s in r.items():
            print(f"| {k} | {s['min']} | {s['p50']} | {s['p95']} | {s['max']} |")
        print()
    print("LATENCY_RESULT " + json.dumps(out))


if __name__ == "__main__":
    main()
