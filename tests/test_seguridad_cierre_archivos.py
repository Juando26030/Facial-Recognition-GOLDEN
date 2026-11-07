"""Cierre de seguridad (6-nov-2026), ángulo «archivos, trabajos y datos personales»: I1/D2 (Excel con topes reales), I2 (rostro de personas sin evento),
I3 (errores sin datos), I5/D5 (importación de digitadores dentro de los 60 s), I6 (imágenes de diseño), D3 (borrar cuentas sin IntegrityError), D4 (nombre del Excel)."""
import io
import re
import time
import zipfile
from datetime import timedelta

import pytest
from openpyxl import Workbook
from PIL import Image

from app import safe_limits
from tests.conftest import login


# ------------------------------------------------------------------ utilidades (puras)
def _xlsx(rows, head=("Identificación", "Nombres", "Apellidos")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(head))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _inflated_dimension(last_row=1048576, last_col="XFD"):
    """Un .xlsx de pocos KB que DECLARA una hoja de 1.048.576 × 16.384 y trae una celda en la última fila: antes costaba minutos de CPU."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Identificación", "Nombres"])
    ws.cell(row=last_row, column=1, value="1012345678")
    raw = io.BytesIO()
    wb.save(raw)
    zin = zipfile.ZipFile(io.BytesIO(raw.getvalue()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]+"/>', f'<dimension ref="A1:{last_col}{last_row}"/>'.encode(), data)
            z.writestr(info, data)
    return out.getvalue()


def _png(size=(12, 8), mode="RGB", fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, fmt)
    return buf.getvalue()


# ------------------------------------------------------------------ I1 / D2: Excel
def test_una_hoja_que_declara_un_millon_de_filas_se_lee_en_un_instante():
    data = _inflated_dimension()
    assert len(data) < 10_000
    t = time.perf_counter()
    rows = safe_limits.xlsx_rows(data, 200, 30)
    assert time.perf_counter() - t < 3
    assert rows[0][:2] == ("Identificación", "Nombres") and len(rows[0]) <= 30


def test_la_carga_masiva_tampoco_cree_la_dimension_declarada():
    t = time.perf_counter()
    rows = safe_limits.xlsx_rows(_inflated_dimension(), 20000, 600)
    assert time.perf_counter() - t < 5 and len(rows) >= 1


def test_se_corta_al_pasar_el_tope_sin_leer_el_resto():
    with pytest.raises(safe_limits.LimitError) as exc:
        safe_limits.xlsx_rows(_xlsx([(str(1000 + i), "N", "A") for i in range(11)]), 10, 30)
    assert "10" in exc.value.message and "máximo" in exc.value.message


def test_filas_vacias_no_cuentan_y_las_columnas_se_acotan():
    rows = safe_limits.xlsx_rows(_xlsx([("1", "a", "b"), (None, None, None), ("2", "c", "d")]), 2, 2)
    assert [r for r in rows[1:]] == [("1", "a"), ("2", "c")]


def test_un_zip_sospechoso_o_que_no_es_excel_se_rechaza_antes_de_abrirlo():
    base = zipfile.ZipFile(io.BytesIO(_xlsx([("1", "a", "b")])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in base.infolist():
            z.writestr(info, base.read(info.filename))
        z.writestr("xl/media/bomba.bin", b"\0" * (20 * 1024 * 1024))          # 20 MB de ceros: razón de compresión ≫ 100
    with pytest.raises(safe_limits.LimitError):
        safe_limits.xlsx_rows(out.getvalue(), 100, 30)
    with pytest.raises(safe_limits.LimitError) as exc:
        safe_limits.xlsx_rows(b"no soy un excel", 100, 30)
    assert "xlsx" in exc.value.message


# ------------------------------------------------------------------ I6: imágenes de diseño
def test_imagen_de_diseno_valida_pasa():
    safe_limits.check_design_image(_png(), ".png")
    safe_limits.check_design_image(_png(fmt="JPEG"), ".jpg")


@pytest.mark.parametrize("content,ext", [
    (b"<html><script>alert(1)</script></html>", ".png"),          # no es imagen
    (_png(fmt="JPEG"), ".png"),                                     # el formato real no coincide con la extensión
    (_png(size=(6000, 6000), mode="L"), ".png"),                    # 36 MP en pocos KB: «bomba» para el quiosco
    (b"", ".png"),
    (_png(), ".svg"),
])
def test_imagen_de_diseno_invalida_se_rechaza(content, ext):
    with pytest.raises(safe_limits.LimitError):
        safe_limits.check_design_image(content, ext)


def test_la_imagen_de_escarapela_ya_no_acepta_cualquier_cosa(client, factory, db):
    factory.staff("admin", "adm1")
    ev = factory.event("creado")
    login(client, "adm1")
    bad = client.post(f"/api/events/{ev.id}/badge-template/upload-image", files={"file": ("fondo.png", b"no soy imagen", "image/png")})
    assert bad.status_code == 400
    ok = client.post(f"/api/events/{ev.id}/badge-template/upload-image", files={"file": ("fondo.png", _png(), "image/png")})
    assert ok.status_code == 200 and ok.json()["storage_path"].endswith(".png")


# ------------------------------------------------------------------ I3: errores sin datos
def test_la_base_no_pone_los_valores_en_los_errores():
    from app.database import engine
    assert engine.hide_parameters is True


def test_motivo_de_fila_sin_texto_de_la_excepcion():
    from sqlalchemy.exc import DataError, IntegrityError
    from app.routers.api import _row_error_reason
    leak = "INSERT INTO users ... [parameters: {'first_name': 'Ana', 'id': '1012345678'}]"
    for exc in (DataError(leak, {}, Exception(leak)), IntegrityError(leak, {}, Exception(leak)), ValueError(leak)):
        reason = _row_error_reason(exc)
        assert "Ana" not in reason and "1012345678" not in reason and "INSERT" not in reason


def test_una_carga_que_falla_no_guarda_ni_muestra_el_texto_de_la_excepcion(factory, db):
    from app import bulk_jobs
    from app.models import BulkJob
    coord = factory.staff("coordinador")
    ev = factory.event("creado")
    job_id = bulk_jobs.create_job(db, ev.id, coord.id)

    def work(_db, _reporter):
        raise RuntimeError("fila de Ana Prueba 1012345678 ana@example.com")
    bulk_jobs.run(job_id, work)
    db.expire_all()
    detail = db.get(BulkJob, job_id).error_detail
    assert "Ana" not in detail and "1012345678" not in detail and "example" not in detail and job_id[:8] in detail


# ------------------------------------------------------------------ I2: rostro de personas sin evento
def test_persona_sin_evento_pierde_el_rostro_a_los_7_dias_de_capturado(factory, db):
    from app import privacy
    from app.models import User
    from app.storage import get_storage, photo_key
    from app.timeutil import utcnow
    factory.tenant("acme")
    for uid, days in (("7001", 8), ("7002", 5)):
        db.add(User(id=uid, tenant_id="acme", first_name="H", last_name="H", face_encoding="[[0.1]]", face_captured_at=utcnow() - timedelta(days=days)))
        get_storage().put(photo_key("acme", uid), b"x")
    db.commit()
    r = privacy.purge_expired(db)
    assert r["people"] == 1 and r["by_cap"] == 0
    db.expire_all()
    assert db.query(User).filter_by(id="7001").one().face_encoding is None and not get_storage().exists(photo_key("acme", "7001"))
    assert db.query(User).filter_by(id="7002").one().face_encoding is not None and get_storage().exists(photo_key("acme", "7002"))


def test_borrar_el_evento_deja_el_rostro_en_cola_de_borrado(client, factory, db):
    from app import privacy
    from app.models import User
    from app.timeutil import utcnow
    factory.staff("super_admin", "adm1")
    ev = factory.event("en_proceso")
    u = factory.person(ev, "7003")
    u.face_encoding, u.face_captured_at = "[[0.1]]", utcnow() - timedelta(days=10)
    db.commit()
    assert privacy.purge_expired(db, dry_run=True)["people"] == 0            # evento abierto: se conserva
    login(client, "adm1")
    ev.status = "finalizado"
    db.commit()
    assert client.post(f"/api/events/{ev.id}/archive").status_code == 200            # Fase 3: borrado definitivo = super_admin + evento archivado
    assert client.delete(f"/api/events/{ev.id}").status_code == 200
    assert privacy.purge_expired(db)["people"] == 1
    db.expire_all()
    assert db.query(User).filter_by(id="7003").one().face_encoding is None


# ------------------------------------------------------------------ D3: borrar cuentas con historial
def _digitador_con_historial(factory, db, ev):
    from app import bulk_jobs
    from app.models import PrintLog
    dig = factory.staff("digitador", "55667788")
    factory.authorize(ev, dig)
    factory.person(ev, "1001")
    db.add(PrintLog(tenant_id=ev.tenant_id, user_id="1001", event_id=ev.id, printed_by_staff_id=dig.id))
    db.commit()
    job_id = bulk_jobs.create_job(db, ev.id, dig.id)
    return dig, job_id


def test_borrado_en_bloque_suelta_impresiones_y_cargas(client, factory, db):
    from app.models import BulkJob, PrintLog, StaffUser
    factory.staff("admin", "adm1")
    ev = factory.event("en_proceso")
    dig, job_id = _digitador_con_historial(factory, db, ev)
    dig_id = dig.id          # el id se lee ANTES: después del borrado la fila ya no existe y releerla da ObjectDeletedError
    login(client, "adm1")
    r = client.post(f"/api/events/{ev.id}/staff-users/purge-temporary")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1
    db.expire_all()
    assert db.query(StaffUser).filter_by(id=dig_id).first() is None
    assert db.query(PrintLog).filter_by(event_id=ev.id).one().printed_by_staff_id is None          # la impresión se conserva, sin «quién»
    assert db.get(BulkJob, job_id).staff_user_id is None


def test_borrar_permanente_tambien_suelta_todo(client, factory, db):
    from app.models import PrintLog, StaffUser
    factory.staff("admin", "adm1")
    ev = factory.event("en_proceso")
    dig, _ = _digitador_con_historial(factory, db, ev)
    dig_id = dig.id
    login(client, "adm1")
    r = client.delete(f"/api/staff/{dig_id}")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(StaffUser).filter_by(id=dig_id).first() is None
    assert db.query(PrintLog).filter_by(event_id=ev.id).one().printed_by_staff_id is None


def test_las_llaves_hacia_staff_se_leen_del_catalogo(db):
    from app import staff_refs
    cols = {(t, c) for t, c, _, _ in staff_refs.staff_fk_columns(db)}
    for need in (("print_logs", "printed_by_staff_id"), ("bulk_jobs", "staff_user_id"), ("web_forms", "created_by_id"),
                 ("area_movements", "registered_by_staff_id"), ("inventory_deliveries", "delivered_by_staff_id")):
        assert need in cols


# ------------------------------------------------------------------ I5 / D5 / D4: importación de digitadores
def test_importar_digitadores_con_dimension_inflada_y_nombres_peligrosos(client, factory, db):
    import bcrypt
    from app.models import StaffUser
    from app.routers import events as ev_router
    factory.staff("admin", "adm1")
    ev = factory.event("creado")
    login(client, "adm1")
    t = time.perf_counter()
    r = client.post(f"/api/events/{ev.id}/staff-users/import", files={"file": ("u.xlsx", _inflated_dimension(), "application/octet-stream")})
    assert r.status_code == 200 and time.perf_counter() - t < 10
    long_name = "Á" * 300
    data = _xlsx([("90111222", "<script>", "x"), ("90111333", long_name, "")])
    r = client.post(f"/api/events/{ev.id}/staff-users/import", files={"file": ("u.xlsx", data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["problems_total"] == 1
    created = db.query(StaffUser).filter_by(username="90111333").one()
    assert len(created.full_name) <= ev_router.STAFF_NAME_MAX
    assert bcrypt.checkpw(b"90111333", created.password_hash.encode())                               # la contraseña sigue siendo la cédula (decisión de Juan David)
    assert created.password_hash.split("$")[2] == f"{ev_router.STAFF_IMPORT_BCRYPT_ROUNDS:02d}"
    assert db.query(StaffUser).filter_by(username="90111222").first() is None


def test_tope_de_filas_cabe_en_una_peticion():
    from app.routers import events as ev_router
    assert ev_router.STAFF_IMPORT_MAX_ROWS <= 200 and ev_router.STAFF_IMPORT_BCRYPT_ROUNDS <= 10
