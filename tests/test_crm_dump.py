"""Lector del volcado de SuiteCRM (app/crm/importer/dump.py): reconoce tablas por sus columnas, descarta basura entre tablas y no depende de la base de datos. Datos 100 % inventados."""
import io

from app.crm.importer import dump

SAMPLE = '''"id","name","date_entered","deleted","account_type","billing_address_city","sic_code"
"a1","EMPRESA UNO","2020-01-01 10:00:00","0","Customer","Bogota","900123456-1"
"a2","EMPRESA DOS","2020-01-02 10:00:00","1",NULL,NULL,NULL
"id_c","codigo_c","estado_c","categoria_c"
"a1","101","Activo","ClienteVIP"
"id","contact_id","account_id","date_modified","deleted"
"r1","c1","a1","2020-01-01 00:00:00","0"
"ie_id","mbox","subject"
"x","INBOX","basura sin id"
"id","parent_id","date_created","created_by","field_name","data_type","before_value_string","after_value_string"
"h1","a1","2020-02-01","u1","name","varchar","VIEJO","NUEVO"
'''


def test_identify_tables_by_columns():
    assert dump.identify(["id", "name", "account_type", "billing_address_city", "sic_code"]) == "accounts"
    assert dump.identify(["id_c", "codigo_c", "estado_c"]) == "accounts_cstm"
    assert dump.identify(["id", "contact_id", "account_id", "deleted"]) == "rel_account_contact"
    assert dump.identify(["id", "zzz"]) is None
    contacts = ["id", "first_name", "last_name", "phone_mobile", "reports_to_id", "lead_source"]
    assert dump.identify(contacts) == "contacts"
    assert dump.identify(contacts + ["converted", "status", "account_name"]) == "leads"          # un lead no se confunde con un contacto


def test_load_returns_only_wanted_tables_and_skips_noise():
    out = dump.load(io.StringIO(SAMPLE), ["accounts", "accounts_cstm", "audit", "rel_account_contact"])
    assert [r["name"] for r in out["accounts"]] == ["EMPRESA UNO", "EMPRESA DOS"]
    assert out["accounts_cstm"][0]["estado_c"] == "Activo"
    assert out["rel_account_contact"][0]["contact_id"] == "c1"
    assert out["audit"][0]["after_value_string"] == "NUEVO"
    assert "ie_id" not in str(out)          # la tabla sin columna id (basura de correo) no se cuela en la anterior
    assert dump.load(io.StringIO(SAMPLE), ["leads"]) == {}


def test_blank_and_clean_treat_null_as_nothing():
    assert dump.blank("NULL") and dump.blank("  ") and dump.blank(None) and not dump.blank("0")
    assert dump.clean(" NULL ") == "" and dump.clean(" x ") == "x"
