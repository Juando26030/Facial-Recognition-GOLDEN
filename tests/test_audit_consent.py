"""`audit_consent_logs`: prueba legal de la autorización biométrica. Solo INSERT; ni el rol de la app ni nadie la modifica; sin llaves foráneas; idempotente."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import consent
from app.database import engine

HASH = "a" * 64


def _rec(db, user="1001", event=1, reason="consent", accepted=True, adult=True, **kw):
    ok = consent.record(db, tenant_id="acme", user_id=user, event_id=event, version="v1.1_kiosk_propio", legal_text_hash=HASH, accepted=accepted, adult=adult, reason=reason, **kw)
    db.commit()
    return ok


def test_record_is_idempotent_by_device_generated_id(db):
    eid = str(uuid.uuid4())
    assert _rec(db, entry_id=eid) is True
    assert _rec(db, entry_id=eid) is False                                   # el reintento sin conexión no duplica
    assert db.execute(text("SELECT count(*) FROM audit_consent_logs")).scalar() == 1


def test_latest_record_decides_the_current_acceptance(db):
    assert consent.has_acceptance(db, "acme", "1001", 1) is False
    _rec(db)
    assert consent.has_acceptance(db, "acme", "1001", 1) is True
    assert consent.has_acceptance(db, "acme", "1001", 2) is False            # otro evento: otra autorización
    _rec(db, reason="revocation", accepted=False)
    assert consent.has_acceptance(db, "acme", "1001", 1) is False            # revocó
    _rec(db, reason="consent")
    assert consent.has_acceptance(db, "acme", "1001", 1) is True             # volvió a aceptar (registro nuevo)
    _rec(db, user="2002", adult=False)
    assert consent.has_acceptance(db, "acme", "2002", 1) is False            # sin declaración de mayoría de edad no cuenta


def test_invalid_reason_is_rejected(db):
    with pytest.raises(ValueError):
        consent.record(db, tenant_id="acme", user_id="1", event_id=1, version="v", legal_text_hash=HASH, accepted=True, adult=True, reason="otra")


@pytest.mark.parametrize("stmt", ["UPDATE audit_consent_logs SET accepted_biometric = false", "DELETE FROM audit_consent_logs", "TRUNCATE audit_consent_logs"])
def test_update_delete_truncate_fail_even_for_the_owner(db, stmt):
    _rec(db)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text(stmt))
    assert db.execute(text("SELECT count(*) FROM audit_consent_logs")).scalar() == 1


def test_the_app_role_only_has_insert_and_select(db):
    """Aplica los permisos reales de scripts/neon_app_role.py a un rol `golden_app` y comprueba que UPDATE/DELETE fallan POR PRIVILEGIO (antes de llegar al disparador)."""
    from scripts import neon_app_role
    with engine.begin() as conn:
        conn.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN CREATE ROLE golden_app NOLOGIN; END IF; END $$"))
    raw = engine.raw_connection()
    try:
        neon_app_role.apply_grants(raw.driver_connection if hasattr(raw, "driver_connection") else raw.connection)
    finally:
        raw.close()
    _rec(db)
    with engine.connect() as conn:
        priv = lambda p: conn.execute(text("SELECT has_table_privilege('golden_app', 'audit_consent_logs', :p)"), {"p": p}).scalar()
        assert priv("INSERT") and priv("SELECT") and not priv("UPDATE") and not priv("DELETE") and not priv("TRUNCATE")
    for stmt in ("UPDATE audit_consent_logs SET reason = 'consent'", "DELETE FROM audit_consent_logs"):
        with pytest.raises(DBAPIError) as e:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL ROLE golden_app"))
                conn.execute(text(stmt))
        assert e.value.orig.pgcode == "42501" and "solo de inserción" not in str(e.value)      # privilegio, no el disparador
    with engine.begin() as conn:                                              # y sí puede insertar y leer
        conn.execute(text("SET LOCAL ROLE golden_app"))
        conn.execute(text("SELECT count(*) FROM audit_consent_logs"))


def test_no_foreign_keys_so_deleting_people_events_or_tenants_never_touches_it(db):
    _rec(db)
    assert db.execute(text("SELECT count(*) FROM pg_constraint WHERE conrelid = 'audit_consent_logs'::regclass AND contype = 'f'")).scalar() == 0
    db.execute(text("DELETE FROM users"))
    db.commit()
    assert db.execute(text("SELECT count(*) FROM audit_consent_logs")).scalar() == 1


def test_cedula_hash_is_stable_and_not_the_plain_cedula():
    assert consent.cedula_hash("1.001 234") == consent.cedula_hash("1001234") and "1001234" not in consent.cedula_hash("1001234")


def test_export_consent_writes_one_persons_records_without_logging_the_cedula(db, monkeypatch, capsys):
    from app import ops_runner
    from app.storage import get_storage
    _rec(db, user="55501")
    _rec(db, user="66602")
    monkeypatch.setenv("CONSENT_EXPORT_CEDULA", "55501")
    assert ops_runner.main("export-consent") == 0
    out = capsys.readouterr().out
    assert "55501" not in out and "1 registros en consent-exports/" in out          # el resultado no lleva la cédula
    key = out.split("en ")[1].split('"')[0]
    data = get_storage().get(key)
    assert b"55501" in data and b"66602" not in data


def test_bench_vector_prints_only_timings(monkeypatch, capsys):
    import types

    from app import biometrics, ops_runner
    calls = []
    monkeypatch.setattr(biometrics, "_fr", lambda: types.SimpleNamespace(face_encodings=lambda img, known_face_locations, num_jitters: calls.append(num_jitters) or [[0.0]]))
    monkeypatch.setenv("BENCH_REPS", "3")
    assert ops_runner.main("bench-vector") == 0
    out = capsys.readouterr().out
    assert "jitters_10_ms" in out and "jitters_25_ms" in out and set(calls) == {1, 10, 25} and calls.count(10) == 3 and calls.count(25) == 3


def test_minors_helpers():
    from datetime import date

    from app import minors
    assert minors.parse_birth("2010-05-01") == date(2010, 5, 1) and minors.parse_birth("01/05/2010") == date(2010, 5, 1)
    assert minors.parse_birth("") is None and minors.parse_birth("2999-01-01") is None and minors.parse_birth("31/02/2000") is None
    assert minors.age_years(date(2008, 10, 7), date(2026, 10, 6)) == 17 and minors.age_years(date(2008, 10, 6), date(2026, 10, 6)) == 18       # cumple 18 ese día
    assert minors.is_minor(date(2008, 10, 7), date(2026, 10, 6)) is True and minors.is_minor(date(2008, 10, 6), date(2026, 10, 6)) is False
    assert minors.is_minor(None) is False                                    # sin fecha no se sabe: lo cubre la declaración de mayoría de edad
