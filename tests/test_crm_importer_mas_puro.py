"""Importador C1c-2: lectura de valores y estructura (corre sin base de datos). Datos SINTÉTICOS."""
import re
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.crm.errors import CrmError
from app.crm.importer import formats, parsing

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("text,expected", [("1.500.000,50", "1500000.50"), ("1,500,000.50", "1500000.50"), ("$ 1.500.000", "1500000"), ("2500.5", "2500.5"), ("1.500", "1500"), ("", "0"), ("1500000", "1500000")])
def test_money_in_both_formats(text, expected):
    assert parsing.parse_money(text) == Decimal(expected)


@pytest.mark.parametrize("bad", ["abc-", "-5", "99999999999999999"])
def test_money_rejects_bad_values(bad):
    with pytest.raises(CrmError):
        parsing.parse_money(bad)


def test_dates_and_datetimes():
    assert parsing.parse_date("2026-12-05") == date(2026, 12, 5)
    assert parsing.parse_date("05/12/2026") == date(2026, 12, 5)
    assert parsing.parse_date("05-12-2026 10:00") == date(2026, 12, 5)
    assert parsing.parse_date("") is None
    assert parsing.parse_datetime("2026-12-03 09:30") == datetime(2026, 12, 3, 9, 30)
    assert parsing.parse_datetime("2026-12-03") == datetime(2026, 12, 3, 0, 0)
    for bad in ("31/02/2026", "mañana", "2026-13-01"):
        with pytest.raises(CrmError):
            parsing.parse_date(bad)
    with pytest.raises(CrmError):
        parsing.parse_datetime("2026-12-03 25:00")


def test_currency_mapping_counts_unknown():
    assert parsing.map_currency("USD", ("COP", "USD")) == ("USD", False)
    assert parsing.map_currency("Dólares", ("COP", "USD")) == ("USD", False)
    assert parsing.map_currency("", ("COP", "USD")) == ("COP", False)
    assert parsing.map_currency("zzz", ("COP", "USD")) == ("COP", True)


def test_stage_mapping():
    stages = [{"id": 1, "name": "Prospecto", "kind": "open"}, {"id": 2, "name": "Cotización enviada", "kind": "open"}, {"id": 8, "name": "Ganó", "kind": "won"}, {"id": 9, "name": "Perdió", "kind": "lost"}]
    assert parsing.stage_for(stages, "Proposal/Price Quote") == (2, "open", True)
    assert parsing.stage_for(stages, "Closed Won") == (8, "won", True)          # renombrada por el admin: se encuentra por tipo
    assert parsing.stage_for(stages, "Closed Lost") == (9, "lost", True)
    assert parsing.stage_for(stages, "Etapa rara") == (1, "open", False)         # no reconocida: primera abierta, y se cuenta
    with pytest.raises(CrmError):
        parsing.stage_for([{"id": 8, "name": "Ganada", "kind": "won"}], "Prospecting")


def test_status_and_stage_tables():
    assert parsing.STATUS_ALIASES["held"] == "done" and parsing.STATUS_ALIASES["not held"] == "cancelled" and parsing.STATUS_ALIASES["planned"] == "planned"
    assert parsing.KIND_ALIASES["call"] == "call" and parsing.KIND_ALIASES["reunion"] == "meeting"
    assert parsing.QUOTE_STAGE_ALIASES["delivered"] == "enviada" and parsing.QUOTE_STAGE_ALIASES["closed accepted"] == "aprobada"
    assert parsing.PROFORMA_STATUS_ALIASES["paid"] == "pagado" and parsing.PROFORMA_STATUS_ALIASES["unpaid"] == "no_pagado"


def test_line_data_defaults_and_caps():
    d = parsing.line_data({"name": "X", "unit_price": "500.000", "discount_percent": "150"})
    assert d["qty"] == "1" and d["tax_percent"] == "19" and Decimal(d["discount_percent"]) == Decimal("100") and Decimal(d["unit_price"]) == Decimal("500000")


def test_new_kinds_headers_in_spanish_and_english():
    es = "ID;Código Proyecto;Nombre;Nombre de la cuenta;Etapa de ventas;Importe\nx1;9001;Evento A;Empresa Uno SAS;Closed Won;1.000.000\n".encode("utf-8")
    rows = list(formats.read_rows("opportunities", es))
    assert rows[0][1]["code"] == "9001" and rows[0][1]["stage"] == "Closed Won" and rows[0][1]["account_name"] == "Empresa Uno SAS"
    en = "Name,Account Name,Sales Stage,Amount\nEvento B,Empresa Uno SAS,Prospecting,10\n".encode("utf-8")
    assert list(formats.read_rows("opportunities", en))[0][1]["amount"] == "10"
    assert list(formats.read_rows("quote_lines", "Nombre,Cantidad,Precio unitario\nA,2,100\n".encode()))[0][1]["qty"] == "2"
    assert list(formats.read_rows("products", "Código,Nombre,Precio\nP1,Servicio,100\n".encode()))[0][1]["sku"] == "P1"


def test_required_columns_fail_without_data():
    for kind, head in (("opportunities", "Nombre\nEvento secreto\n"), ("quotes", "Título\nSecreto\n"), ("proformas", "Total\n999\n"), ("quote_lines", "Cantidad\n7\n"), ("activities", "Estado\nPlanned\n")):
        with pytest.raises(CrmError) as e:
            list(formats.read_rows(kind, head.encode()))
        assert "secreto" not in str(e.value).lower() and "999" not in str(e.value)
    with pytest.raises(CrmError):
        formats.check_headers("opportunities", b"Nombre\nA\n")


def test_every_kind_has_aliases_and_required():
    assert set(formats.ALIASES) == set(formats.REQUIRED) == {"accounts", "contacts", "products", "opportunities", "activities", "quotes", "quote_lines", "proformas"}
    for kind, req in formats.REQUIRED.items():
        assert all(k in formats.ALIASES[kind] for k in req)


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_runner_order_locks_and_cleanup():
    runner, router = _src("app/crm/importer/runner.py"), _src("app/routers/crm_import.py")
    assert runner.index('"products", "opportunities", "activities", "quotes", "proformas"') > 0
    assert all(k in runner for k in ("more.import_products", "more.import_opportunities", "more.import_activities", "more.import_quotes", "more.import_proformas"))
    assert "delete_prefix" in runner and "finally" in runner
    for k in ("products", "opportunities", "activities", "quotes", "quote_lines", "proformas"):
        assert f"{k}: Optional[UploadFile]" in router
    assert "apply_enabled()" in router and "CONFIRM_WORD" in router and 'prev.mode != "dry_run"' in router and "sha256" in router


def test_importer_never_triggers_effects_or_logs_data():
    more = _src("app/crm/importer/more.py")
    assert "on_won" not in more and "move_stage" not in more and "create_event_for" not in more        # una ganada importada NO crea eventos
    assert "outcome=kind" in more and "legacy_sugar_id=legacy" in more
    assert "begin_nested" in more                                                                        # un SAVEPOINT por fila
    assert not re.search(r"\blogger\.|\bprint\(|logging\.", more)                                        # nada de datos personales en logs
    assert "audit" not in more.lower() or "no se escribe" in more.lower()
    for call in ("bump_floor(db, \"event\"", "bump_floor(db, \"quote\"", "bump_floor(db, \"proforma\""):
        assert call in more
    assert "from app.crm.importer import formats, parsing" in more


def test_rejections_never_carry_values():
    more = _src("app/crm/importer/more.py")
    calls = re.findall(r"_reject\(rejected, lineno, (.+)\)$", more, flags=re.M)
    assert len(calls) >= 10 and set(calls) <= {"str(e)", "_generic(e)"}                                # solo el motivo de CrmError o el texto genérico


def test_synthetic_generator_makes_all_files(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts/crm_make_synthetic_suitecrm.py"), str(tmp_path), "12"], check=True)
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {"cuentas.csv", "contactos.csv", "productos.csv", "oportunidades.csv", "actividades.csv", "cotizaciones.csv", "lineas_cotizacion.csv", "proformas.csv"}
    kinds = {"cuentas.csv": "accounts", "contactos.csv": "contacts", "productos.csv": "products", "oportunidades.csv": "opportunities", "actividades.csv": "activities",
             "cotizaciones.csv": "quotes", "lineas_cotizacion.csv": "quote_lines", "proformas.csv": "proformas"}
    for fname, kind in kinds.items():
        rows = list(formats.read_rows(kind, (tmp_path / fname).read_bytes()))
        assert rows, fname
    opp = list(formats.read_rows("opportunities", (tmp_path / "oportunidades.csv").read_bytes()))
    for _n, r in opp:
        assert parsing.parse_date(r["expected_close"]) and parsing.parse_money(r["amount"]) > 0


def test_page_has_a_file_input_per_kind():
    html, js = _src("templates/crm_importar.html"), _src("static/js/crm_importar.js")
    for k in ("accounts", "contacts", "products", "opportunities", "activities", "quotes", "quote_lines", "proformas"):
        assert f'data-kind="{k}"' in html and f'{k}: "' in js
    assert "alert(" not in js and "innerHTML" not in js
