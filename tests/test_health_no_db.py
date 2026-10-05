"""/health (lo que miran UptimeRobot y Google en producción) NO toca la base: ni una sentencia SQL y ni una conexión del pool, para no mantener despierto el cómputo de Neon (docs/15, monitores).
`/ready` es lo contrario a propósito (sonda de arranque)."""
from sqlalchemy import event

from app.database import engine


def _statements(client, path, **kw):
    seen, conns = [], []
    def on_exec(conn, cursor, statement, *a): seen.append(statement)
    def on_checkout(*a): conns.append(1)
    event.listen(engine, "before_cursor_execute", on_exec)
    event.listen(engine, "checkout", on_checkout)
    try:
        r = client.get(path, **kw)
    finally:
        event.remove(engine, "before_cursor_execute", on_exec)
        event.remove(engine, "checkout", on_checkout)
    return r, seen, conns


def test_health_runs_no_sql_and_takes_no_connection(client):
    for path in ("/health", "/healthz"):
        r, seen, conns = _statements(client, path)
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert seen == [] and conns == [], f"{path} tocó la base: {seen}"


def test_health_is_still_fine_with_a_session_cookie_and_forwarded_headers(client):
    r, seen, conns = _statements(client, "/health", headers={"X-Forwarded-For": "1.2.3.4, 34.1.1.1", "Cookie": "__session=basura; session=basura"})
    assert r.status_code == 200 and seen == [] and conns == []


def test_ready_does_touch_the_database_on_purpose(client):
    r, seen, conns = _statements(client, "/ready")
    assert any("SELECT 1" in s.upper() for s in seen) or conns, "/ready debe consultar la base (es la sonda de arranque)"
