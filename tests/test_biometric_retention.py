"""Retención biométrica: 7 días tras finalizar TODOS los eventos de la persona, tope de 180 días, idempotencia y errores de almacenamiento."""
from datetime import timedelta

from app import privacy
from app.models import EventAttendee, User
from app.storage import get_storage, photo_key
from app.timeutil import utcnow
from tests.conftest import login


def _person(db, uid, *events, captured_days_ago=1):
    tenant = events[0].tenant_id
    db.add(User(id=uid, tenant_id=tenant, first_name="N", last_name="A", face_encoding="[[0.1]]", biometric_consent_at=utcnow(),
                biometric_consent_source="kiosko", face_captured_at=utcnow() - timedelta(days=captured_days_ago)))
    db.flush()
    for e in events:
        db.add(EventAttendee(event_id=e.id, user_id=uid, tenant_id=tenant))
    get_storage().put(photo_key(tenant, uid), b"x")
    db.commit()


def _finalized(factory, db, days_ago, **kw):
    ev = factory.event("finalizado", **kw)
    ev.finalized_at = utcnow() - timedelta(days=days_ago)
    db.commit()
    return ev


def _has(db, uid, tenant="acme"):
    db.expire_all()
    u = db.query(User).filter_by(id=uid, tenant_id=tenant).one()
    return bool(u.face_encoding), get_storage().exists(photo_key(tenant, uid))


def test_person_in_one_event_is_purged_only_after_7_days(factory, db):
    old, recent = _finalized(factory, db, 8), _finalized(factory, db, 6)
    _person(db, "1001", old)
    _person(db, "2002", recent)
    r = privacy.purge_expired(db)
    assert (r["people"], r["objects"], r["errors"], r["by_cap"]) == (1, 1, 0, 0)
    assert _has(db, "1001") == (False, False) and _has(db, "2002") == (True, True)
    assert db.query(User).filter_by(id="1001").one().first_name == "N"                       # todo lo demás se conserva


def test_person_in_two_events_waits_for_the_last_one(factory, db):
    old, open_ev = _finalized(factory, db, 30), factory.event("en_proceso")
    _person(db, "1001", old, open_ev)
    assert privacy.purge_expired(db)["people"] == 0 and _has(db, "1001") == (True, True)     # el otro evento sigue abierto
    open_ev.status = "finalizado"
    open_ev.finalized_at = utcnow() - timedelta(days=3)
    db.commit()
    assert privacy.purge_expired(db)["people"] == 0                                           # cerró hace 3 días: aún no
    open_ev.finalized_at = utcnow() - timedelta(days=7, minutes=1)
    db.commit()
    assert privacy.purge_expired(db)["people"] == 1 and _has(db, "1001") == (False, False)


def test_reopening_restarts_the_clock_and_finalizing_stamps_it(factory, db):
    ev = factory.event("en_proceso")
    assert ev.finalized_at is None
    ev.status = "finalizado"
    db.commit()
    assert abs((utcnow() - ev.finalized_at).total_seconds()) < 60
    ev.finalized_at = utcnow() - timedelta(days=20)
    db.commit()
    _person(db, "1001", ev)
    ev.status = "en_proceso"                                                                  # reabierto
    db.commit()
    assert ev.finalized_at is None and privacy.purge_expired(db)["people"] == 0
    ev.status = "finalizado"                                                                  # vuelve a cerrar: 7 días desde ahora, no desde antes
    db.commit()
    assert privacy.purge_expired(db)["people"] == 0 and _has(db, "1001") == (True, True)


def test_cap_of_180_days_applies_even_with_an_open_event_and_orphans_only_by_cap(factory, db):
    open_ev = factory.event("en_proceso")
    _person(db, "1001", open_ev, captured_days_ago=181)
    _person(db, "2002", open_ev, captured_days_ago=179)
    db.add(User(id="3003", tenant_id="acme", first_name="H", last_name="H", face_encoding="[[0.1]]", face_captured_at=utcnow() - timedelta(days=5)))
    db.commit()                                                                                # sin ningún evento: solo el tope la borraría
    r = privacy.purge_expired(db)
    assert (r["people"], r["by_cap"]) == (1, 1)
    assert _has(db, "1001") == (False, False) and _has(db, "2002") == (True, True) and _has(db, "3003")[0] is True


def test_purge_is_idempotent_and_batches(factory, db):
    ev = _finalized(factory, db, 9)
    for i in range(5):
        _person(db, f"10{i}", ev)
    r = privacy.purge_expired(db, batch=2)
    assert r["people"] == 5 and r["objects"] == 5
    assert privacy.purge_expired(db, batch=2) == {"people": 0, "objects": 0, "errors": 0, "by_cap": 0}


def test_storage_failure_keeps_the_encoding_and_retries_next_run(factory, db, monkeypatch):
    ev = _finalized(factory, db, 9)
    _person(db, "1001", ev)
    storage = get_storage()
    real = storage.delete
    monkeypatch.setattr(type(storage), "delete", lambda self, key: (_ for _ in ()).throw(OSError("bucket caído")))
    r = privacy.purge_expired(db)
    assert (r["people"], r["errors"]) == (0, 1) and _has(db, "1001") == (True, True)          # ni encoding sin foto ni al revés
    monkeypatch.setattr(type(storage), "delete", lambda self, key: real(key))
    assert privacy.purge_expired(db)["people"] == 1 and _has(db, "1001") == (False, False)


def test_dry_run_touches_nothing(factory, db):
    ev = _finalized(factory, db, 9)
    _person(db, "1001", ev)
    assert privacy.purge_expired(db, dry_run=True)["people"] == 1 and _has(db, "1001") == (True, True)


def test_ops_purge_step_reports_only_counts_and_fails_on_errors(factory, db, monkeypatch):
    import pytest
    from app import ops_runner
    ev = _finalized(factory, db, 9)
    _person(db, "1001", ev)
    out = ops_runner.purge()
    assert '"people": 1' in out and "1001" not in out
    monkeypatch.setattr(privacy, "purge_expired", lambda db_: {"people": 0, "objects": 0, "errors": 2, "by_cap": 0})
    with pytest.raises(RuntimeError, match="2 error"):
        ops_runner.purge()


def test_delete_photos_button_is_admin_only_and_needs_the_event_name(client, factory, db):
    factory.staff("coordinador", "coord1")
    factory.staff("admin", "adm1")
    ev = factory.event("en_proceso", facial_enabled=True)
    _person(db, "1001", ev)
    login(client, "coord1")
    assert client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm_name": ev.name}).status_code == 403
    assert 'id="purgePhotosBtn"' not in client.get(f"/kiosk/{ev.id}/estadisticas").text
    client.post("/logout")
    login(client, "adm1")
    assert 'id="purgePhotosBtn"' in client.get(f"/kiosk/{ev.id}/estadisticas").text
    assert client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm_name": "no"}).status_code == 400
    assert _has(db, "1001") == (True, True)
    assert client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm_name": ev.name}).json()["deleted"] == 1
    assert _has(db, "1001") == (False, False)


def test_a_manual_purge_keeps_people_in_other_open_facial_events_only(client, factory, db):
    factory.staff("admin", "adm1")
    ev = _finalized(factory, db, 1)
    open_facial = factory.event("en_proceso", facial_enabled=True)
    open_plain = factory.event("en_proceso", facial_enabled=False)
    _person(db, "1001", ev, open_facial)                                                        # otro evento abierto CON rostro: se conserva
    _person(db, "2002", ev, open_plain)                                                         # otro evento abierto sin rostro: no lo necesita, se borra
    _accept(db, open_facial, "1001")                                                            # (regla 2026-10-06) solo cuenta si aceptó en ese otro evento
    login(client, "adm1")
    r = client.post(f"/api/events/{ev.id}/biometrics/purge", json={"confirm_name": ev.name}).json()
    assert (r["deleted"], r["kept_in_other_events"]) == (1, 1)
    assert _has(db, "1001") == (True, True) and _has(db, "2002") == (False, False)


def test_backup_lifecycle_keeps_hourly_3_days_and_daily_30_days():
    import json
    rules = json.load(open("deploy/gcs-lifecycle.json"))["rule"]
    ages = {tuple(r["condition"]["matchesPrefix"]): r["condition"].get("age") for r in rules if "age" in r["condition"]}
    assert ages == {("db/hourly/",): 3, ("db/",): 30}


def test_resending_the_same_status_does_not_restart_the_clock(client, factory, db):
    factory.staff("coordinador", "coord1")
    ev = factory.event("finalizado")
    ev.finalized_at = utcnow() - timedelta(days=5)
    db.commit()
    login(client, "coord1")
    assert client.patch(f"/api/events/{ev.id}", json={"status": "finalizado", "notes": "x"}).status_code == 200
    db.expire_all()
    assert (utcnow() - ev.finalized_at) > timedelta(days=4)


# ---- regla de la auditora (2026-10-06): «otro evento abierto» solo cuenta si la persona aceptó en él
def _accept(db, ev, uid):
    from app import consent
    consent.record(db, tenant_id=ev.tenant_id, user_id=uid, event_id=ev.id, version="v", legal_text_hash="a" * 64, accepted=True, adult=True, reason="consent")
    db.commit()


def test_an_open_event_without_acceptance_does_not_hold_the_face(factory, db):
    old, open_ev = _finalized(factory, db, 8), factory.event("en_proceso")
    _person(db, "1001", old, open_ev)
    _accept(db, old, "1001")                                                       # aceptó solo en el que ya cerró hace 8 días
    assert privacy.purge_expired(db)["people"] == 1 and _has(db, "1001") == (False, False)


def test_an_open_event_with_acceptance_holds_it_until_that_event_is_also_over_by_7_days_and_reopening_resets(factory, db):
    old, other = _finalized(factory, db, 30), factory.event("en_proceso")
    _person(db, "1001", old, other)
    _accept(db, old, "1001")
    _accept(db, other, "1001")
    assert privacy.purge_expired(db)["people"] == 0 and _has(db, "1001") == (True, True)
    other.status = "finalizado"
    other.finalized_at = utcnow() - timedelta(days=6)
    db.commit()
    assert privacy.purge_expired(db)["people"] == 0                                # 6 días: todavía no
    other.status = "en_proceso"                                                    # se reabre: el reloj se reinicia (finalized_at vuelve a NULL)
    db.commit()
    db.refresh(other)
    assert other.finalized_at is None and privacy.purge_expired(db)["people"] == 0
    other.status = "finalizado"
    db.commit()
    assert privacy.purge_expired(db, now=utcnow() + timedelta(days=8))["people"] == 1       # 8 días después del cierre nuevo (fecha simulada)


def test_the_180_day_cap_still_applies_with_an_accepted_open_event(factory, db):
    open_ev = factory.event("en_proceso")
    _person(db, "1001", open_ev, captured_days_ago=181)
    _accept(db, open_ev, "1001")
    r = privacy.purge_expired(db)
    assert r["people"] == 1 and r["by_cap"] == 1 and _has(db, "1001") == (False, False)


def test_manual_event_purge_keeps_people_only_where_they_accepted_in_the_other_open_event(factory, db):
    ev = factory.event("en_proceso", facial_enabled=True)
    other = factory.event("en_proceso", facial_enabled=True)
    _person(db, "1001", ev, other)
    _person(db, "2002", ev, other)
    _accept(db, other, "1001")
    r = privacy.purge_event(db, ev)
    assert r["deleted"] == 1 and r["kept_in_other_events"] == 1 and _has(db, "1001") == (True, True) and _has(db, "2002") == (False, False)


def test_system_status_warns_about_events_that_ended_but_were_never_finalized(factory, db):
    from datetime import date

    from app import ops
    late = factory.event("en_proceso", end_date=date.today() - timedelta(days=4))
    factory.event("en_proceso", end_date=date.today() - timedelta(days=2))          # terminó hace poco: todavía no es alerta
    factory.event("finalizado", end_date=date.today() - timedelta(days=40))        # ya finalizado: tampoco
    r = ops.check_unfinished_events(db)
    assert r["level"] == "yellow" and r["data"]["events"] == [late.event_code] and "7 días" in r["reason"]
    assert any(i["id"] == "unfinished_events" for i in ops.system_status(db)["items"])
