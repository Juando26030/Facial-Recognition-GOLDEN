"""R3-08 (Fase 3): entradas fuera de rango dan 4xx, nunca 500. Las de «fuente» no usan base; las demás usan el Postgres de pruebas."""
from pathlib import Path

from tests.conftest import PASSWORD, login

ROOT = Path(__file__).resolve().parent.parent


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_source_limit_offset_are_validated_and_badge_asset_catches_value_error():
    api = _src("app/routers/api.py")
    assert "limit: Optional[int] = Query(None, ge=1" in api and "offset: int = Query(0, ge=0)" in api
    b = _src("app/routers/badges.py")
    chunk = b[b.index("def get_badge_asset("):b.index("def _require_printable")]
    assert "except ValueError" in chunk and "status_code=404" in chunk


def test_password_longer_than_72_bytes_is_a_clear_problem():
    from app import security
    assert security.password_problem("Aq7" + "x" * 69, strict=True) is None            # 72 bytes
    assert "demasiado larga" in security.password_problem("Aq7" + "x" * 70, strict=True)       # 73 bytes
    assert "demasiado larga" in security.password_problem("ñ" * 40 + "A1", strict=True)         # 82 bytes en UTF-8 (42 caracteres)


def test_users_endpoint_rejects_negative_limit(client, factory):
    factory.staff("coordinador", "coo")
    ev = factory.event()
    login(client, "coo")
    assert client.get(f"/api/users?event_id={ev.id}&limit=-1").status_code == 422
    assert client.get(f"/api/users?event_id={ev.id}&offset=-5").status_code == 422
    assert client.get(f"/api/users?event_id={ev.id}&limit=10").status_code == 200


def test_badge_asset_with_dotdot_is_404(client, factory):
    factory.staff("coordinador", "coo")
    login(client, "coo")
    assert client.get("/api/badge-assets/%2e%2e/x.png").status_code == 404
    assert client.get("/api/badge-assets/acme/inexistente.png").status_code == 404


def test_long_password_is_rejected_with_400_on_staff_creation_and_reset(client, factory):
    factory.staff("admin", "adm")
    login(client, "adm")
    r = client.post("/api/staff", json={"username": "nuevo1", "password": "Aq7" + "x" * 80, "role": "admin", "full_name": "Nuevo Uno", "phone": "3001112233"})
    assert r.status_code in (400, 422), r.text
    assert PASSWORD
