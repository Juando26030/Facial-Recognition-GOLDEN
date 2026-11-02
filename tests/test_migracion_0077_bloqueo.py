"""Migración 0077: el `ALTER TABLE access_logs` no puede encolar los ingresos de la puerta. Con una transacción larga abierta sobre `access_logs`, la migración espera como mucho `lock_timeout`
(reintentando), falla con un mensaje claro sin dejar nada a medias, y un lector que llega mientras espera NO queda bloqueado más allá de ese tope. Además, los permisos de `golden_app`."""
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

from tests.conftest import TEST_URL

DB = "golden_lock_test"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _url(name):
    return urlunsplit(urlsplit(TEST_URL)._replace(path="/" + name)).replace("postgresql+psycopg2://", "postgresql://")


def _alembic(target, **env):
    e = {**os.environ, "DATABASE_URL": _url(DB), "DIRECT_DATABASE_URL": _url(DB), **{k: str(v) for k, v in env.items()}}
    return subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=ROOT, env=e, capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def scratch():
    admin = psycopg2.connect(_url("postgres"))
    admin.autocommit = True
    admin.cursor().execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    admin.cursor().execute(f"CREATE DATABASE {DB}")
    cur = admin.cursor()
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'golden_app'")
    made_role = cur.fetchone() is None
    if made_role:
        cur.execute("CREATE ROLE golden_app NOLOGIN")                      # solo para esta prueba (se borra al final); si ya existía, no se toca
    r = _alembic("0076_print_mode")
    assert r.returncode == 0, r.stderr[-800:]
    yield
    cur.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    if made_role:
        cur.execute("DROP ROLE golden_app")
    admin.close()


def _exists(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def test_a_long_transaction_on_access_logs_makes_the_migration_fail_cleanly_without_queueing_readers(scratch):
    holder = psycopg2.connect(_url(DB))                                   # una transacción larga: lee `access_logs` y no termina (ACCESS SHARE)
    holder.cursor().execute("SELECT count(*) FROM access_logs")
    waits = []

    def reader():                                                          # un ingreso de la puerta que llega mientras la migración espera el bloqueo
        time.sleep(0.6)
        c = psycopg2.connect(_url(DB))
        t0 = time.perf_counter()
        c.cursor().execute("SELECT count(*) FROM access_logs")
        waits.append(time.perf_counter() - t0)
        c.close()
    th = threading.Thread(target=reader)
    th.start()
    t0 = time.perf_counter()
    r = _alembic("head", MIGRATION_LOCK_TIMEOUT_S=1.5, MIGRATION_LOCK_ATTEMPTS=2, MIGRATION_LOCK_PAUSE_S=0.5)
    th.join()
    elapsed = time.perf_counter() - t0
    assert r.returncode != 0 and "access_logs` estuvo ocupada" in r.stderr and "No se cambió nada" in r.stderr, r.stderr[-600:]
    assert waits and waits[0] < 1.6, waits                                 # el lector esperó, como mucho, el tope de la migración (sin tope habría esperado a la transacción larga)
    assert elapsed < 60
    check = psycopg2.connect(_url(DB))
    cur = check.cursor()
    assert not _exists(cur, "SELECT to_regclass('public.event_status_changes') IS NOT NULL")                     # nada quedó a medias: ni la tabla…
    assert not _exists(cur, "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='access_logs' AND column_name='doubtful_reason')")      # …ni la columna
    cur.execute("SELECT version_num FROM alembic_version")
    assert cur.fetchone()[0] == "0076_print_mode"
    check.close()
    holder.rollback()
    holder.close()


def test_when_the_lock_frees_up_between_attempts_the_migration_completes_and_grants_the_app_role(scratch):
    holder = psycopg2.connect(_url(DB))
    holder.cursor().execute("SELECT count(*) FROM access_logs")
    threading.Timer(1.2, lambda: (holder.rollback(), holder.close())).start()          # la transacción larga termina entre el primer y el segundo intento
    r = _alembic("head", MIGRATION_LOCK_TIMEOUT_S=0.8, MIGRATION_LOCK_ATTEMPTS=5, MIGRATION_LOCK_PAUSE_S=0.6)
    assert r.returncode == 0, r.stderr[-800:]
    c = psycopg2.connect(_url(DB))
    k = c.cursor()
    assert _exists(k, "SELECT has_table_privilege('golden_app', 'event_status_changes', 'INSERT') AND has_table_privilege('golden_app', 'event_status_changes', 'SELECT')")
    assert _exists(k, "SELECT has_sequence_privilege('golden_app', 'event_status_changes_id_seq', 'USAGE')")
    k.execute("GRANT SELECT, INSERT ON access_logs TO golden_app")                                       # (access_logs ya tiene sus permisos de tabla en la vida real: aquí solo se prueba la columna)
    c.commit()
    assert _exists(k, "SELECT has_column_privilege('golden_app', 'access_logs', 'doubtful_reason', 'SELECT')")
    k.execute("SELECT version_num FROM alembic_version")
    assert k.fetchone()[0] == "0077_event_status_changes"
    c.close()
