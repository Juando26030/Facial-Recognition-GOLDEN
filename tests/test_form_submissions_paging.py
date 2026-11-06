"""Tabla de respuestas del editor: paginación, buscador (cédula/nombre) y filtro por cupo, resueltos en el servidor.
Las primeras pruebas son puras (sin base); las de `client` corren en CI."""
import json
import re
from pathlib import Path

from app import formlib

ROOT = Path(__file__).resolve().parent.parent


def _design(fields):          # mismo diseño que tests/test_forms.py (copiado para que las pruebas puras no necesiten la base)
    return {"theme": {}, "fields": {f["id"]: f for f in fields}, "rows": [{"items": [f["id"]]} for f in fields]}


def _basic_fields():
    return [{"id": "cedula", "type": "text_short", "label": "Cédula", "key": "id", "required": True}, {"id": "nombres", "type": "text_short", "label": "Nombres", "key": "first_name", "required": True},
            {"id": "apellidos", "type": "text_short", "label": "Apellidos", "key": "last_name", "required": True}, {"id": "correo", "type": "email", "label": "Correo", "key": "email", "required": True}]


DESIGN = _design(_basic_fields())


# ------------------------------------------------------------------ puras
def test_page_size_accepts_20_50_100_and_clamps_the_rest():
    assert [formlib.answers_page_size(x) for x in (20, "50", 100)] == [20, 50, 100]
    assert formlib.answers_page_size(None) == 50 and formlib.answers_page_size("abc") == 50 and formlib.answers_page_size(0) == 50 and formlib.answers_page_size(-5) == 50
    assert formlib.answers_page_size(30) == 50
    assert formlib.answers_page_size(101) == 100 and formlib.answers_page_size(5000) == 100


def test_paging_bounds_and_offsets():
    assert formlib.answers_paging(0, 1, 50) == {"page": 1, "page_size": 50, "pages": 1, "offset": 0}
    assert formlib.answers_paging(5000, 3, 100) == {"page": 3, "page_size": 100, "pages": 50, "offset": 200}
    assert formlib.answers_paging(101, 1, 50)["pages"] == 3
    assert formlib.answers_paging(101, 99, 50)["page"] == 3         # pedir más allá de la última devuelve la última
    assert formlib.answers_paging(101, 0, 50)["page"] == 1 and formlib.answers_paging(101, "x", 50)["page"] == 1
    assert formlib.answers_paging(40, 2, 20) == {"page": 2, "page_size": 20, "pages": 2, "offset": 20}


def _m(q, data, pid=None):
    return formlib.answers_match(formlib.answers_parse_query(q), data, pid, formlib.answers_search_fields(DESIGN))


ROW = {"cedula": "1.016.100-329", "nombres": "María José", "apellidos": "Peña Amaya", "correo": "maria@x.co"}


def test_search_fields_use_identity_keys():
    assert formlib.answers_search_fields(DESIGN) == {"ids": ["cedula"], "names": ["nombres", "apellidos"]}


def test_empty_query_means_no_filter():
    assert formlib.answers_parse_query("   ") is None and formlib.answers_parse_query(None) is None and formlib.answers_parse_query("..") is None
    assert _m("", ROW) is True


def test_digits_match_exact_or_prefix_of_the_document_only():
    assert _m("1016100329", ROW) and _m("1016", ROW) and _m("1.016.100", ROW) and _m(" 1016 100 ", ROW)
    assert not _m("16100329", ROW)          # no es «contiene»
    assert not _m("1016100330", ROW)
    assert _m("0001016", {"cedula": "1016100329"})       # ceros a la izquierda
    assert _m("555", {"cedula": "x"}, pid="555123")      # cédula guardada en person_id
    assert not _m("1234", {"cedula": "9", "telefono": "1234567"})     # un número en otro campo no cuenta si el formulario marca el documento


def test_name_match_is_accent_and_case_insensitive_by_word_prefix_in_any_order():
    assert _m("maria", ROW) and _m("MARÍA JOSE", ROW) and _m("peña", ROW) and _m("pena maria", ROW) and _m("ma", ROW)
    assert not _m("maya", ROW)              # «Amaya» no empieza por «maya»
    assert not _m("maria maria", ROW)       # cada palabra escrita usa una palabra distinta
    assert not _m("correo", ROW) and not _m("maria@x", ROW)       # el correo no es nombre ni documento


def test_without_identity_keys_any_text_value_is_searched():
    fields = formlib.answers_search_fields(_design([{"id": "a", "type": "text_short", "label": "A"}]))
    assert fields == {"ids": [], "names": []}
    parsed = formlib.answers_parse_query("ana")
    assert formlib.answers_match(parsed, {"a": "Ana Ruiz"}, None, fields) and not formlib.answers_match(parsed, {"a": "Luis"}, None, fields)
    assert formlib.answers_match(formlib.answers_parse_query("123"), {"a": "123456"}, None, fields)


def test_quota_groups_by_variable():
    design = _design([{"id": "ciudad", "type": "text_short", "label": "Ciudad"}, {"id": "tipo", "type": "text_short", "label": "Tipo"}])
    rules = [{"id": "r1", "conds": [{"field": "ciudad"}]}, {"id": "r2", "conds": [{"field": "ciudad"}, {"field": "tipo"}]}]
    assert formlib.answers_quota_groups(rules, design) == {"r1": "Ciudad", "r2": ""}


# ------------------------------------------------------------------ estáticas de la plantilla
def test_template_has_search_quota_filter_pager_and_keeps_old_ids():
    html = (ROOT / "templates" / "kiosk_formulario_editor.html").read_text(encoding="utf-8")
    for ident in ("ansTests", "ansHead", "ansBody", "ansInfo", "repBtn", "repBtnAll", "ansSearch", "ansSearchClear", "ansQuota", "ansPrev", "ansNext", "ansSize"):
        assert f'id="{ident}"' in html, ident
    assert 'aria-label="Vaciar búsqueda"' in html and "gw-search__clear" in html
    assert "page_size" in html and "include_tests" in html and "}, 300)" in html            # debounce de 300 ms
    assert "Mostrando ${from}–${to} de ${d.total}" in html and "sin filtros" in html
    assert "data-delsub" in html and "fitTable($('ansBody')" in html
    assert not re.search(r"submissions\?include_tests=\$\{withTests\}`\)", html)           # ya no pide todo de una vez
    assert "css/p-respuestas.css" in html


def test_answers_css_uses_tokens_only():
    css = (ROOT / "static" / "css" / "p-respuestas.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css) and "!important" not in css


# ------------------------------------------------------------------ con base (CI)
def _form(client, factory):
    from tests.conftest import login
    from tests.test_forms import _create, _event, _put, _status
    ev = _event(client, factory)
    factory.staff("admin", "adm1")
    login(client, "adm1")
    f = _create(client, ev)
    fields = _basic_fields()[:3] + [{"id": "ciudad", "type": "text_short", "label": "Ciudad"}]
    rules = [{"label": "Bogotá", "match": "all", "limit": 100, "conds": [{"field": "ciudad", "op": "equals", "value": "Bogotá"}]},
             {"label": "Cali", "match": "all", "limit": 100, "conds": [{"field": "ciudad", "op": "equals", "value": "Cali"}]}]
    assert _put(client, ev, f, design=_design(fields), settings={"quotas": {"rules": rules}}).status_code == 200
    _status(client, ev, f, manual_status="activo")
    return ev, f


def _seed(db, ev, f, n):
    from app.models import FormSubmission
    from app import formsvc
    from app.models import WebForm
    rules = formsvc.quota_rules(db.get(WebForm, f["id"]))
    for i in range(n):
        city = "Bogotá" if i % 2 == 0 else "Cali"
        data = {"cedula": str(1000 + i), "nombres": "Ana" if i == 0 else f"Persona{i}", "apellidos": "Pérez", "ciudad": city}
        db.add(FormSubmission(form_id=f["id"], event_id=ev.id, data_json=json.dumps(data), person_id=data["cedula"], is_test=False, status="confirmed", quota_keys=formsvc.quota_keys_for(rules, data)))
    db.commit()


def _get(client, ev, f, **params):
    r = client.get(f"/api/events/{ev.id}/forms/{f['id']}/submissions", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_server_pages_newest_first_without_the_old_2000_cap(client, factory, db):
    ev, f = _form(client, factory)
    _seed(db, ev, f, 120)
    d = _get(client, ev, f)
    assert (d["total"], d["total_all"], d["page"], d["page_size"], d["pages"], len(d["rows"])) == (120, 120, 1, 50, 3, 50)
    ids = [r["id"] for r in d["rows"]]
    assert ids == sorted(ids, reverse=True)
    d3 = _get(client, ev, f, page=3)
    assert len(d3["rows"]) == 20 and d3["rows"][-1]["id"] < ids[-1]
    assert len(_get(client, ev, f, page_size=999)["rows"]) == 100 and _get(client, ev, f, page=50)["page"] == 3


def test_search_by_cedula_and_name_and_quota_filter(client, factory, db):
    ev, f = _form(client, factory)
    _seed(db, ev, f, 20)
    assert _get(client, ev, f, q="1005")["total"] == 1
    assert _get(client, ev, f, q="1005")["total_all"] == 20
    assert _get(client, ev, f, q="ANA")["total"] == 1 and _get(client, ev, f, q="perez")["total"] == 20
    d = _get(client, ev, f)
    assert [q["label"] for q in d["quotas"]] == ["Bogotá", "Cali"] and [q["count"] for q in d["quotas"]] == [10, 10]
    bog = d["quotas"][0]["id"]
    assert _get(client, ev, f, quota=bog)["total"] == 10
    assert _get(client, ev, f, quota=bog, q="ana")["total"] == 1
    assert client.get(f"/api/events/{ev.id}/forms/{f['id']}/submissions", params={"quota": "no-existe"}).status_code == 400
