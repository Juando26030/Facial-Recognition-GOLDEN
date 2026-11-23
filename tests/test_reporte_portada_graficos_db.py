"""Fase 10 (E): el reporte real del evento trae Portada → Reporte → Gráficos (→ Historial de cambios). Con base de datos (Cloud Shell). La persona PRUEBA no cuenta en los totales."""
from datetime import datetime

from openpyxl import load_workbook

from app.models import AccessLog
from app.reports import ReportManager
from tests.conftest import login


def test_real_report_has_cover_report_and_charts_without_the_test_person(client, factory, db, tmp_path):
    coord = factory.staff("coordinador", "coord")
    ev = factory.event("en_proceso", coordinator=coord, city="Bogotá", location="Ágora")
    for uid in ("1001", "1002", "1003"):
        factory.person(ev, uid)
    factory.person(ev, "PRUEBA", first_name="Prueba")
    db.add(AccessLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, record_type="Nuevo", registration_method="tradicional", timestamp=datetime(2026, 11, 12, 15, 0, 5)))
    db.commit()
    login(client, "coord")
    client.patch(f"/api/users/1002?event_id={ev.id}", json={"role": "Gerente"})
    out = tmp_path / "r.xlsx"
    ReportManager.generate_excel_report(db, ev.id, ev.tenant_id, str(out))
    wb = load_workbook(out)
    assert wb.sheetnames == ["Portada", "Reporte", "Gráficos", "Gráficos registrados", "Gráficos no registrados", "Historial de cambios", "Personas registradas", "Personas no registradas"]
    assert wb.active.title == "Portada"
    cover = [str(c.value) for row in wb["Portada"].iter_rows() for c in row if c.value is not None]
    assert "3" in cover and "1" in cover                          # 3 personas (sin PRUEBA), 1 registrada
    assert len(wb["Portada"]._images) >= 1                         # al menos el logo de Golden
    ids = [r[0] for r in wb["Reporte"].iter_rows(values_only=True) if r and r[0]]
    assert "PRUEBA" not in ids
    assert len(wb["Gráficos"]._charts) >= 1
