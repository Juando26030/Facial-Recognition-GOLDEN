"""Importador C1c: núcleo puro con archivos SINTÉTICOS (corre sin base de datos)."""
import pytest

from app.crm.errors import CrmError
from app.crm.importer import formats, scoring


def test_headers_in_spanish_or_english_and_any_delimiter():
    es = "Nombre;Número de cuenta;Ciudad\nEmpresa Uno SAS;1001;Bogotá\n".encode("utf-8")
    en = "Name,Account Number,City\nEmpresa Uno SAS,1001,Bogota\n".encode("cp1252")
    for raw in (es, en):
        rows = list(formats.read_rows("accounts", raw))
        assert rows[0][0] == 2 and rows[0][1]["name"] == "Empresa Uno SAS" and rows[0][1]["code"] == "1001"


def test_missing_required_column_is_an_error_without_data():
    with pytest.raises(CrmError) as e:
        list(formats.read_rows("accounts", b"Ciudad,Telefono\nBogota,300\n"))
    assert "300" not in str(e.value) and "nombre" in str(e.value).lower()


def test_limits_empty_and_blank_rows():
    with pytest.raises(CrmError):
        list(formats.read_rows("accounts", b""))
    with pytest.raises(CrmError):
        formats.decode(b"x" * (formats.MAX_FILE_BYTES + 1))
    raw = b"Nombre\nA\n\n,\nB\nC\n"
    assert [r[1]["name"] for r in formats.read_rows("accounts", raw, limit=2)] == ["A", "B"]


def test_company_key_ignores_accents_case_and_legal_forms():
    assert scoring.company_key("Hotel Ejemplo S.A.S.") == scoring.company_key("HOTEL EJEMPLÓ SAS") == "hotel ejemplo"


def test_score_and_buckets():
    left = [("a", "Hotel Ejemplo SAS"), ("b", "Cámara Ficticia"), ("c", "Zzz Distinta"), ("d", "Constructora Norte")]
    right = [(1, "HOTEL EJEMPLO"), (2, "Camara Ficticia de Comercio"), (3, "Constructora Norte Ltda"), (4, "Constructora Nortes")]
    got = {l: (r, s, b) for l, r, s, b in scoring.pair_all(left, right)}
    assert got["a"][0] == 1 and got["a"][2] == "seguro"
    assert got["c"] == (None, got["c"][1], "sin_pareja") and got["c"][1] < 70
    assert got["d"][2] == "dudoso"          # dos candidatos casi iguales: sin margen
    assert got["b"][2] in ("dudoso", "seguro") and got["b"][0] == 2
