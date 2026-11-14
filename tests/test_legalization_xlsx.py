"""Excel de legalizaciones (PLANTILLA-LEG.xlsx): estructura, tablas que crecen, totales y comprobantes.
No usa base de datos. La comparación numérica recalcula con LibreOffice y se salta si no está instalado."""
import io
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from app import legalization_xlsx as L

D = date(2026, 11, 5)
HEADER = dict(fecha_legalizacion=D, responsable="JOSE SIERRA", cc="1143401306", cod_evento="23736",
              evento="MOSCA LABORATORIO - Congreso Nacional", ciudad="MONTENEGRO", fecha_evento=D, anticipo=None)


def _wb(lines, header=HEADER):
    return openpyxl.load_workbook(io.BytesIO(L.build_workbook(header, lines)))


def _many(kind, n, **kw):
    return [dict(kind=kind, date=D, name=f"{kind}-{i}", tax_id=str(1000 + i), amount=1000 * (i + 1), **kw) for i in range(n)]


def test_plantilla_tiene_las_hojas_del_formato_y_sin_auditoria():
    wb = openpyxl.load_workbook(L.TEMPLATE_PATH)
    assert wb.sheetnames == [L.S_RES, L.S_HOSP, L.S_TAXI, L.S_DIG, L.S_ALIM, L.S_OTROS, L.S_SOP]
    assert all(len(ws._images) == 1 for ws in wb.worksheets), "cada hoja conserva su logo"
    assert "digitadores(as)" in wb[L.S_RES]["B23"].value
    assert "iñas" not in wb[L.S_RES]["B23"].value and "PagoNi" not in "".join(wb.sheetnames)


def test_encabezado_y_formulas_del_resumen():
    wb = _wb(_many("digitador", 3))
    ws = wb[L.S_RES]
    assert (ws["C6"].value, ws["C7"].value, ws["C8"].value) == ("JOSE SIERRA", 1143401306, 23736)
    assert ws["C3"].value is None, "el consecutivo lo pone el área administrativa"
    assert ws["C23"].value == "=+PagoDigitadores!H29"
    assert ws["C29"].value == "=IF(C24>=C13,0,C13-C24)", "«a devolver» sale en positivo"


def test_los_terminales_se_suman_en_su_rubro():
    wb = _wb([dict(kind="taxi_terminal", date=D, concept="DESMONTAJE", amount=20000)])
    assert wb[L.S_HOSP]["J26"].value == 20000 and wb[L.S_HOSP]["I26"].value == "DESMONTAJE"
    assert wb[L.S_RES]["C19"].value == f"=+'{L.S_HOSP}'!J35"


def test_tablas_que_se_llenan_crecen_y_reescriben_los_totales():
    lines = _many("hospedaje", 8) + _many("pasaje", 6) + _many("taxi_terminal", 12) + _many("taxi_ciudad", 30) \
        + _many("digitador", 25) + _many("otro", 35)
    wb = _wb(lines)
    h = wb[L.S_HOSP]
    # hospedaje 8 filas (+2): total en 18; pasajes empieza en 21, 6 filas (+2): total en 27; terminales 12 filas (+3)
    assert h["J18"].value == "=SUM(J10:J17)" and h["A18"].value == "TOTAL"
    assert h["J27"].value == "=SUM(J21:J26)"
    assert h["J42"].value == "=SUM(J30:J41)"          # terminales: 12 filas (+3), empiezan en 30
    res = wb[L.S_RES]
    assert res["C19"].value == f"=+'{L.S_HOSP}'!J42"
    assert res["C17"].value == f"=+'{L.S_HOSP}'!J18" and res["C20"].value == f"=+'{L.S_HOSP}'!J27"
    assert wb[L.S_TAXI]["M39"].value == "=SUM(M9:M38)" and res["C18"].value == f"=+'{L.S_TAXI}'!M39"
    assert wb[L.S_DIG]["H34"].value == "=SUM(H9:H33)" and wb[L.S_DIG].print_area.endswith("$H$34")
    assert wb[L.S_OTROS]["J44"].value == "=SUM(J9:J43)"
    assert wb[L.S_DIG]["A33"].value == 25, "la numeración sigue en las filas agregadas"


def test_comprobante_de_soportes_por_cada_taxi_sin_recibo():
    lines = [
        dict(kind="taxi_ciudad", date=D, name="A", tax_id="1", amount=50000, support=False, origin="X", destination="Y"),
        dict(kind="taxi_ciudad", date=D, name="B", tax_id="2", amount=30000, support=True),
        dict(kind="taxi_terminal", date=D, name="C", tax_id="3", amount=20000, support=False),
    ]
    ws = _wb(lines)[L.S_SOP]
    assert len(ws._images) == 2
    assert (ws["A7"].value, ws["D9"].value, ws["B11"].value, ws["B13"].value) == ("A", 50000, "X", "Y")
    assert ws["C19"].value.strip() == "Nº    2", "el segundo comprobante empieza 14 filas más abajo"
    assert ws["A21"].value == "C" and ws["D30"].value == "=SUM(D23:D29)"


def test_alimentacion_suma_las_comidas_o_toma_el_valor_directo():
    lines = [dict(kind="alimentacion", date=D, name="a", lunch=40000, snack=12000),
             dict(kind="alimentacion", date=D, name="b", amount=7777)]
    ws = _wb(lines)[L.S_ALIM]
    assert ws["M9"].value == "=SUM(I9:L9)" and ws["O9"].value == "=M9"
    assert ws["J9"].value == 40000 and ws["L9"].value == 12000
    assert ws["O10"].value == 7777 and ws["O26"].value == "=SUM(O9:O25)"


def test_summarize_y_nombre_del_archivo():
    s = L.summarize(_many("taxi_ciudad", 2) + _many("digitador", 1) + [dict(kind="alimentacion", lunch=500, snack=250)], anticipo=10000)
    assert s["taxis_ciudad"] == 3000 and s["digitadores"] == 1000 and s["alimentacion"] == 750
    assert s["total"] == 4750 and s["neto_sin_digitadores"] == 3750 and s["devolver"] == 5250 and s["reembolsar"] == 0
    assert L.file_name(23736, "MOSCA LABORATORIO - Congreso Nacional de Vigilancia") == "LEG-COD_23736-MOSCA_LABORATORIO.xlsx"
    assert L.file_name(5, "") == "LEG-COD_5.xlsx"


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice no está instalado")
def test_totales_calculados_por_excel_coinciden_con_summarize():
    lines = _many("hospedaje", 8) + _many("pasaje", 6) + _many("taxi_terminal", 12) + _many("taxi_ciudad", 30, support=False) \
        + _many("digitador", 25) + _many("otro", 35) \
        + [dict(kind="alimentacion", date=D, name=f"a{i}", breakfast=1000 * (i + 1), lunch=500) for i in range(20)]
    header = dict(HEADER, anticipo=2000000)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "s.xlsx"
        src.write_bytes(L.build_workbook(header, lines))
        subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(Path(tmp) / "lo"), str(src)],
                       capture_output=True, timeout=170, check=True)
        ws = openpyxl.load_workbook(Path(tmp) / "lo" / "s.xlsx", data_only=True)[L.S_RES]
    s = L.summarize(lines, 2000000)
    got = [ws[c].value for c in ("C17", "C18", "C19", "C20", "C21", "C22", "C23", "C24", "C25", "C28", "C29")]
    exp = [s["hospedaje"], s["taxis_ciudad"], s["traslado_terminales"], s["pasajes"], s["alimentacion"], s["otros"],
           s["digitadores"], s["total"], s["neto_sin_digitadores"], s["reembolsar"], s["devolver"]]
    assert got == pytest.approx(exp)
