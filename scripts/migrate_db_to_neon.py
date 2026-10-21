"""Base de la VM → Neon, con conteo de filas por tabla antes y después (doc 15, día del cambio). Probar primero contra la rama STAGING.

    # desde la VM (tiene pg_dump/psql 18), origen en vivo:
    python scripts/migrate_db_to_neon.py --source-url "$VM_DATABASE_URL" --target-owner-secret golden-db-owner-url-production --migrate
    # desde un respaldo (.sql o .sql.gz) contra staging, vaciándola antes:
    python scripts/migrate_db_to_neon.py --source-dump golden_db_20260926.sql.gz --target-env-file .env.staging --wipe --migrate

Qué hace, en orden:
  1. Exige que el rol `golden_app` ya exista en el destino (`scripts/neon_app_role.py`) y que el destino esté vacío (`--wipe` lo vacía:
     borra el esquema public entero; pide escribir el nombre de la base salvo con `--yes`).
  2. Vuelca el origen con pg_dump 18 (`--no-owner --no-privileges`) o lee el respaldo, y lo pasa directo a psql 18 (`ON_ERROR_STOP`,
     una sola transacción: o entra todo o nada), sin archivos intermedios. Por el camino quita `OWNER TO`, `GRANT`, `REVOKE` y
     `ALTER DEFAULT PRIVILEGES` (en la VM `golden_app` es dueño de todo; en Neon el dueño es el rol de migraciones) y cuenta las filas
     de cada tabla en los bloques COPY. Con `--source-url` además cuenta en el origen vivo y exige que coincida con el volcado.
  3. Cuenta en el destino, tabla por tabla. Cualquier diferencia → código de salida 1.
  4. Con `--migrate`: `alembic upgrade head` con el dueño (conexión directa) y vuelve a contar.
  5. Aplica los permisos de `golden_app`.

Herramientas: `PG_DUMP` y `PSQL` (por defecto `pg_dump` y `psql`; deben ser versión 18: los volcados de la VM traen `\\restrict`).
Sin 18 instalado: `PSQL="docker run --rm -i -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE -e PGCHANNELBINDING postgres:18 psql"`.
Las cadenas de conexión nunca se imprimen: van a las herramientas como variables de entorno de libpq."""
import argparse
import gzip
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import Counter
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.neon_app_role import APP_ROLE, apply_grants, env_value, gcloud_secret, read_env  # noqa: E402

DROP = re.compile(r"^(ALTER\s.*\sOWNER TO\s|GRANT\s|REVOKE\s|ALTER DEFAULT PRIVILEGES\s)")
COPY = re.compile(r"^COPY (?:public\.)?\"?([\w]+)\"? .* FROM stdin;$")

COUNT_SQL = """
SELECT c.relname,
       (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY 1"""


def libpq_env(url: str) -> dict:
    u = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    env = {"PGHOST": u.hostname or "", "PGPORT": str(u.port or 5432), "PGUSER": unquote(u.username or ""),
           "PGPASSWORD": unquote(u.password or ""), "PGDATABASE": u.path.lstrip("/")}
    if q.get("sslmode"):
        env["PGSSLMODE"] = q["sslmode"]
    if q.get("channel_binding"):
        env["PGCHANNELBINDING"] = q["channel_binding"]
    return {**os.environ, **env}


def counts(url: str) -> dict:
    conn = psycopg2.connect(url, connect_timeout=20)
    try:
        with conn.cursor() as cur:
            cur.execute(COUNT_SQL)
            return dict(cur.fetchall())
    finally:
        conn.close()


def tool(name: str, default: str) -> list:
    parts = shlex.split(os.environ.get(name, default), posix=os.name != "nt")
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]      # Windows: shlex deja las comillas


def check_version(cmd: list, env: dict) -> None:
    out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, env=env).stdout
    major = re.search(r"(\d+)(?:\.\d+)", out or "")
    if not major or int(major.group(1)) < 18:
        sys.exit(f"Se necesita la versión 18 de {cmd[-1]} (hay: {out.strip() or 'ninguna'}). Ver PSQL/PG_DUMP en la ayuda.")


def source_lines(args, env_src):
    """Líneas del volcado (de pg_dump en vivo o del respaldo) en BYTES: pasan a psql tal cual (en texto, Windows cambiaría los saltos de línea)."""
    if args.source_dump:
        opener = gzip.open if args.source_dump.endswith(".gz") else open
        with opener(args.source_dump, "rb") as fh:
            yield from fh
        return
    dump = subprocess.Popen(tool("PG_DUMP", "pg_dump") + ["--no-owner", "--no-privileges", "--format=plain"], stdout=subprocess.PIPE, env=env_src)
    yield from dump.stdout
    if dump.wait() != 0:
        raise SystemExit("pg_dump falló: no se restauró nada (la transacción del destino se deshace sola).")


def restore(args, env_src, env_dst) -> Counter:
    """Pasa el volcado filtrado a psql y devuelve {tabla: filas} contadas en los bloques COPY."""
    psql = subprocess.Popen(tool("PSQL", "psql") + ["-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", "-"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env_dst)
    err = []
    threading.Thread(target=lambda: err.extend(psql.stderr), daemon=True).start()
    threading.Thread(target=lambda: psql.stdout.read(), daemon=True).start()
    rows, table, dropped = Counter(), None, 0
    try:
        for line in source_lines(args, env_src):
            if table is not None:
                if line.rstrip(b"\r\n") == b"\\.":
                    table = None
                else:
                    rows[table] += 1
                psql.stdin.write(line)
                continue
            text = line.decode("utf8", "replace")
            if DROP.match(text):
                dropped += 1
                continue
            m = COPY.match(text.rstrip("\r\n"))
            if m:
                table = m.group(1)
                rows.setdefault(table, 0)
            psql.stdin.write(line)
        psql.stdin.close()
    except BrokenPipeError:
        pass
    if psql.wait() != 0:
        sys.exit("psql se detuvo en un error (ON_ERROR_STOP): el destino quedó como estaba. Detalle:\n" + b"".join(err[-15:]).decode("utf8", "replace"))
    print(f"Restaurado en una sola transacción; se omitieron {dropped} sentencias de dueños/permisos de la VM.")
    return rows


def compare(expected: dict, got: dict, title: str) -> bool:
    names = sorted(set(expected) | set(got))
    width = max([len(n) for n in names] + [5])
    print(f"\n{title}\n{'tabla'.ljust(width)}  {'antes':>8}  {'después':>8}")
    ok = True
    for n in names:
        a, b = expected.get(n), got.get(n)
        mark = "" if a == b else "   <-- DIFERENTE"
        ok &= a == b
        print(f"{n.ljust(width)}  {str(a if a is not None else '-'):>8}  {str(b if b is not None else '-'):>8}{mark}")
    print(f"{'TOTAL'.ljust(width)}  {sum(v or 0 for v in expected.values()):>8}  {sum(v or 0 for v in got.values()):>8}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-url", help="base de la VM (en vivo)")
    src.add_argument("--source-dump", help="respaldo .sql o .sql.gz")
    dst = ap.add_mutually_exclusive_group(required=True)
    dst.add_argument("--target-env-file", help="archivo con DIRECT_DATABASE_URL del dueño (p. ej. .env.staging)")
    dst.add_argument("--target-owner-secret", help="secreto de Secret Manager con la cadena directa del dueño")
    ap.add_argument("--wipe", action="store_true", help="vaciar el destino antes (borra el esquema public)")
    ap.add_argument("--yes", action="store_true", help="no pedir confirmación para --wipe")
    ap.add_argument("--migrate", action="store_true", help="alembic upgrade head después de restaurar")
    args = ap.parse_args()

    target = env_value(read_env(args.target_env_file)[0], "DIRECT_DATABASE_URL") if args.target_env_file else gcloud_secret(args.target_owner_secret)
    tu = urlsplit(target)
    if not target or tu.username == APP_ROLE or "-pooler" in (tu.hostname or ""):
        sys.exit("El destino debe ser la conexión DIRECTA (sin -pooler) del rol DUEÑO: el volcado crea tablas.")
    env_dst = libpq_env(target)
    env_src = libpq_env(args.source_url) if args.source_url else os.environ.copy()
    check_version(tool("PSQL", "psql"), env_dst)
    if args.source_url:
        check_version(tool("PG_DUMP", "pg_dump"), env_src)

    conn = psycopg2.connect(target, connect_timeout=20)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        if not cur.fetchone():
            sys.exit(f"Falta el rol {APP_ROLE} en el destino: corre primero scripts/neon_app_role.py.")
        cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        existing = cur.fetchone()[0]
        if existing and not args.wipe:
            sys.exit(f"El destino ya tiene {existing} tablas. Usa --wipe para vaciarlo (solo en staging o en una base nueva).")
        if existing:
            db = tu.path.lstrip("/")
            if not args.yes and input(f"Se BORRARÁ todo el esquema public de «{db}» en {tu.hostname}. Escribe el nombre de la base: ").strip() != db:
                sys.exit("Cancelado.")
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
            print(f"Destino vaciado ({existing} tablas).")
    conn.close()

    live = counts(args.source_url) if args.source_url else None
    t0 = time.time()
    dumped = restore(args, env_src, env_dst)
    print(f"Tiempo de volcado + restauración: {time.time() - t0:.1f} s")
    ok = True
    if live is not None:
        ok &= compare(live, dict(dumped), "Origen en vivo vs. filas del volcado")
    after = counts(target)
    ok &= compare(dict(dumped), after, "Filas por tabla: volcado (antes) vs. Neon (después)")

    if args.migrate:
        env = {**os.environ, "DIRECT_DATABASE_URL": target, "DATABASE_URL": target}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ok &= compare(after, {k: v for k, v in counts(target).items() if k in after}, "Después de las migraciones (mismas tablas)")

    conn = psycopg2.connect(target, connect_timeout=20)
    try:
        apply_grants(conn)
    finally:
        conn.close()
    print(f"\nPermisos de {APP_ROLE} aplicados.")
    if not ok:
        sys.exit("\nHAY DIFERENCIAS en los conteos: no usar este destino hasta revisarlas.")
    print("Conteos idénticos en todas las tablas.")


if __name__ == "__main__":
    main()
