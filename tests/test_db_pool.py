"""Abrir una conexión a Neon cuesta ~500 ms (TLS + channel binding): la app debe reutilizar las del pool del proceso y nunca abrir una por petición."""
from sqlalchemy import event

from app.database import engine


def test_requests_reuse_pooled_connections(client):
    assert engine.pool._pre_ping and engine.pool.size() >= 1
    client.get("/readyz")                                   # calienta el pool
    opened = []
    listener = lambda *a: opened.append(1)                  # noqa: E731
    event.listen(engine, "connect", listener)
    try:
        for _ in range(30):
            assert client.get("/readyz").status_code == 200
    finally:
        event.remove(engine, "connect", listener)
    assert opened == []
