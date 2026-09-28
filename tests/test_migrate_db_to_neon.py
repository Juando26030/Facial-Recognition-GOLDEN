"""Filtro del volcado de la VM → Neon: quita dueños/permisos de la VM, NUNCA toca los datos de los COPY, y cuenta las filas por tabla."""
import gzip
import sys
from types import SimpleNamespace

from scripts import migrate_db_to_neon as mig

DUMP = b"""SET statement_timeout = 0;
CREATE TABLE public.tenants (id text);
ALTER TABLE public.tenants OWNER TO golden_app;
COPY public.tenants (id) FROM stdin;
acme
GRANT ALL ON everything TO nadie
\\.
COPY public."users" (id) FROM stdin;
\\.
GRANT ALL ON SCHEMA public TO golden_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO golden_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SEQUENCE public.x_id_seq OWNED BY public.x.id;
"""


def test_filter_keeps_data_drops_vm_ownership_and_counts_rows(tmp_path, monkeypatch):
    src, out = tmp_path / "d.sql.gz", tmp_path / "recibido.sql"
    src.write_bytes(gzip.compress(DUMP))
    monkeypatch.setenv("PSQL", f'"{sys.executable}" -c "import sys, shutil; shutil.copyfileobj(sys.stdin.buffer, open(r\'{out}\', \'wb\'))"')
    rows = mig.restore(SimpleNamespace(source_dump=str(src)), {}, None)
    got = out.read_bytes()
    assert rows == {"tenants": 2, "users": 0}
    assert b"GRANT ALL ON everything TO nadie" in got                     # dato de un COPY: pasa tal cual
    assert b"OWNER TO golden_app" not in got and b"GRANT ALL ON SCHEMA" not in got and b"ALTER DEFAULT PRIVILEGES" not in got and b"REVOKE" not in got
    assert b"OWNED BY public.x.id" in got and b"\r\n" not in got          # OWNED BY (secuencias) se conserva; sin saltos de Windows
