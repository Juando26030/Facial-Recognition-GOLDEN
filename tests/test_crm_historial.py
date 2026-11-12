"""CRM C1a: registro de cambios con la forma de person_history (app/crm/history.py). La comparación (`diff`) es pura; `record` necesita PostgreSQL."""
import pytest

from app import models as m
from app.crm import history, normalize


def test_diff_lists_only_what_changed_in_the_given_fields():
    before = {"name": "Acme", "city": "Bogotá", "phone": ""}
    after = {"name": "Acme SAS", "city": "Bogotá", "phone": "300"}
    assert history.diff(before, after) == [("name", "Acme", "Acme SAS"), ("phone", "", "300")]
    assert history.diff(before, after, ["city"]) == []


def test_fields_cover_the_expected_columns_and_never_the_ids_or_codes():
    for f in ("name", "status", "billing_city", "payment_term", "agency_percent"):
        assert f in history.ACCOUNT_FIELDS
    for f in ("first_name", "email", "mobile", "job_title"):
        assert f in history.CONTACT_FIELDS
    assert "code" not in history.ACCOUNT_FIELDS and "tenant_id" not in history.ACCOUNT_FIELDS and "legacy_sugar_id" not in history.ACCOUNT_FIELDS


def _acc(db, **kw):
    a = m.CrmAccount(code=1, name="Acme", name_norm=normalize("Acme"), **kw)
    db.add(a)
    db.commit()
    return a


def test_record_writes_one_row_per_changed_field_with_who_when_and_source(db, factory):
    staff = factory.staff("comercial", "com")
    a = _acc(db, billing_city="Bogotá")
    before = history.snapshot(a, "account")
    a.name, a.billing_city, a.phone = "Acme SAS", "Medellín", "3001112233"
    n = history.record(db, a, "account", before, staff_id=staff.id)
    db.commit()
    assert n == 3
    rows = {r.field_key: r for r in db.query(m.CrmChangeLog).filter_by(entity="account", entity_id=a.id)}
    assert set(rows) == {"name", "billing_city", "phone"}
    assert (rows["billing_city"].old_value, rows["billing_city"].new_value) == ("Bogotá", "Medellín")
    assert rows["phone"].old_value is None and rows["phone"].new_value == "3001112233"            # vacío antes → NULL
    assert all(r.changed_by_id == staff.id and r.source == "edit" and r.changed_at is not None for r in rows.values())


def test_record_writes_nothing_when_nothing_changed(db):
    a = _acc(db)
    before = history.snapshot(a, "account")
    assert history.record(db, a, "account", before) == 0
    db.commit()
    assert db.query(m.CrmChangeLog).count() == 0


def test_values_are_cut_to_500_characters_and_contacts_have_their_own_entity(db):
    a = _acc(db)
    c = m.CrmContact(account_id=a.id, first_name="Ana", full_name_norm="ana")
    db.add(c)
    db.commit()
    before = history.snapshot(c, "contact")
    c.notes = "x" * 900
    c.email = "ana@ejemplo.test"
    history.record(db, c, "contact", before, source="import")
    db.commit()
    rows = {r.field_key: r for r in db.query(m.CrmChangeLog).filter_by(entity="contact", entity_id=c.id)}
    assert len(rows["notes"].new_value) == 500 and rows["email"].source == "import"


def test_an_unknown_source_is_rejected(db):
    a = _acc(db)
    with pytest.raises(ValueError):
        history.record(db, a, "account", history.snapshot(a, "account"), source="otra")
