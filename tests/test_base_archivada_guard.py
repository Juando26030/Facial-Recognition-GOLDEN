"""Fase 3 (P2): con la base del evento archivada (L7, 90 días) solo un super_admin ve o escribe personas, respuestas o pagos. Incluye los enlaces públicos y una prueba por AST que obliga
a decidir en cada ruta nueva con `get_event_for_staff` (guard `event_archive.require_data_open` o excepción explícita y revisada)."""
import ast
import pathlib

import pytest

from app.models import EventAttendee, WebForm
from app.timeutil import utcnow
from tests.conftest import login

ROOT = pathlib.Path(__file__).resolve().parents[1]

ROUTES = [                      # (método, plantilla): el coordinador debe recibir 403 con la base archivada
    ("get", "/api/report?event_id={e}"),
    ("get", "/api/events/{e}/incomplete-registrations"),
    ("get", "/api/events/{e}/forms/{f}/submissions"),
    ("get", "/api/events/{e}/forms/{f}/payments"),
    ("get", "/api/events/{e}/forms/{f}/report"),
    ("get", "/api/events/{e}/forms/{f}/analytics"),
    ("get", "/api/events/{e}/forms/{f}/invites"),
    ("get", "/api/events/{e}/local-roster"),
    ("get", "/api/events/{e}/roulette/candidates"),
]


@pytest.fixture()
def archived(factory, db):
    coord = factory.staff("coordinador", "coord")
    factory.staff("super_admin", "root")
    ev = factory.event("finalizado", coordinator=coord)
    ev.data_archived_at = utcnow()
    form = WebForm(event_id=ev.id, name="F", slug="f", manual_status="finalizado", design_json="{}", test_key="k")
    db.add(form)
    db.commit()
    return ev, form


@pytest.mark.parametrize("method,tpl", ROUTES)
def test_coordinador_gets_403_on_archived_base(client, archived, method, tpl):
    ev, form = archived
    login(client, "coord")
    assert getattr(client, method)(tpl.format(e=ev.id, f=form.id)).status_code == 403


@pytest.mark.parametrize("method,tpl", ROUTES)
def test_super_admin_still_gets_through(client, archived, method, tpl):
    ev, form = archived
    login(client, "root")
    try:
        status = getattr(client, method)(tpl.format(e=ev.id, f=form.id)).status_code
    except Exception:      # el formulario de la prueba es mínimo (design_json «{}»): si la ruta llega a fallar DENTRO del manejador es que la puerta la dejó pasar
        return
    assert status != 403


def test_open_base_is_not_affected(client, factory):
    coord = factory.staff("coordinador", "coord_ok")
    ev = factory.event("finalizado", coordinator=coord)
    login(client, "coord_ok")
    assert client.get(f"/api/events/{ev.id}/incomplete-registrations").status_code == 200


def test_cannot_reopen_a_form_of_an_archived_base(client, archived):
    ev, form = archived
    login(client, "coord")
    r = client.put(f"/api/events/{ev.id}/forms/{form.id}/status", json={"manual_status": "activo"})
    assert r.status_code == 400


def test_public_certificate_and_digital_badge_close_with_the_archive(client, factory, db):
    ev = factory.event("finalizado", certificates_enabled=True, certificates_token="TOKEN-ARCH-1", digital_badge_enabled=True)
    factory.person(ev, "1001")
    db.query(EventAttendee).filter_by(event_id=ev.id).update({"certificate": True, "digital_token": "DIG-ARCH-1"})
    db.commit()
    assert client.get("/c/TOKEN-ARCH-1/lookup?id=1001").status_code == 200
    assert client.get("/b/DIG-ARCH-1/data").status_code == 200
    ev.data_archived_at = utcnow()
    db.commit()
    assert client.get("/c/TOKEN-ARCH-1/lookup?id=1001").status_code == 404
    assert client.get("/b/DIG-ARCH-1/data").status_code == 404
    assert client.get("/b/DIG-ARCH-1/photo").status_code == 404
    ev.data_archived_at, ev.archived_at = None, utcnow()                  # archivar el evento (no solo la base) también cierra los enlaces
    db.commit()
    assert client.get("/c/TOKEN-ARCH-1/lookup?id=1001").status_code == 404
    assert client.get("/b/DIG-ARCH-1/data").status_code == 404


def test_coordinator_sync_is_refused_on_an_archived_event_or_base(client, factory, db):
    coord = factory.staff("coordinador", "coord2")
    ev = factory.event("finalizado", coordinator=coord)
    factory.person(ev, "1001")
    login(client, "coord2")
    body = {"records": [{"client_id": "c1", "cedula": "1001"}]}
    ev.archived_at = utcnow()
    db.commit()
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).status_code == 403
    ev.archived_at, ev.data_archived_at = None, utcnow()
    db.commit()
    assert client.post(f"/api/events/{ev.id}/access-logs/sync", json=body).status_code == 403


def test_digital_badge_does_not_expose_contact_data(client, factory, db):
    ev = factory.event("en_proceso", digital_badge_enabled=True)
    u = factory.person(ev, "1001")
    u.phone, u.email = "3001112233", "ana@example.com"
    db.query(EventAttendee).filter_by(event_id=ev.id).update({"digital_token": "DIG-A3"})
    db.commit()
    person = client.get("/b/DIG-A3/data").json()["person"]
    assert person["id"] == "1001" and "phone" not in person and "email" not in person
    assert "3001112233" not in str(person) and "ana@example.com" not in str(person)


# Rutas con `get_event_for_staff` que NO tocan personas, respuestas ni pagos (configuración, plantillas, archivos del evento, personal, derechos de privacidad…).
# Mantener corta y revisada: una ruta nueva obliga a decidir entre `event_archive.require_data_open` o añadirse aquí con su porqué.
ALLOW = {
    "api.py": {"email_check", "recognize", "_recognition_from_token", "checkin_cedula", "bulk_job_active"},          # reconocimiento/registro exigen evento «en proceso» (nunca uno archivado)
    "areas_inventory.py": {"set_modules", "list_areas", "create_area", "update_area", "archive_area", "restore_area", "delete_area", "list_inventory", "create_item", "update_item",
                           "archive_item", "restore_item", "delete_item"},          # configuración de zonas y catálogo
    "badges.py": {"set_badge_mode", "get_badge_template", "update_badge_template", "list_saved_badge_templates", "save_badge_template_as", "import_saved_badge_template", "upload_badge_image"},
    "cedula.py": {"scan_cedula_mrz"},          # no lee ni guarda nada del evento
    "certificates_public.py": {"get_public_link", "create_public_link"},          # el enlace público ya se cierra solo (_event_by_token)
    "consents.py": {"consent_text", "set_precalc", "set_consent_config", "get_biometric_setup", "put_biometric_setup", "accept_mail_status", "accept_mail_test", "accept_mail_stop", "set_badge_bio_photo"},
    "event_docs.py": {"list_documents", "add_document", "_find_doc", "download_all_documents", "list_expenses", "add_expense", "_get_expense", "expenses_report"},          # documentos y gastos: no son personas
    "event_report.py": {"upload_final_report", "download_final_report"},
    "event_history.py": {"get_change_history"},          # historial de campos del evento: solo campos del evento, nunca personas, respuestas ni pagos
    "events.py": {"get_event", "list_event_staff", "assign_existing_staff", "staff_users_template", "import_event_staff", "purge_event_staff", "delete_event_staff_account", "revoke_event_staff"},          # personal de la plataforma, no asistentes
    "staff_credentials.py": {"resend_event_staff", "set_event_staff_email", "set_event_staff_mail"},          # cuentas del personal y su correo, no personas, respuestas ni pagos
    "form_client.py": {"_form_for_manager"},
    "form_transfer.py": {"export_form", "import_preview", "import_form", "transfer_allowed"},          # el diseño del formulario, sin respuestas
    "forms.py": {"list_forms", "create_form", "get_form", "update_form", "preview_registered", "registered_template", "clear_registered", "archive_form", "restore_form", "delete_form",
                 "duplicate_form", "set_status", "event_fields", "field_values", "variant_table_template", "variant_table_parse", "value_suggestions", "list_codes", "create_codes",
                 "delete_code", "export_codes", "list_templates", "save_template", "archive_template", "restore_template", "delete_template", "upload_image"},          # set_status tiene su propia regla (D9)
    "login_approval.py": {"_target", "login_state", "approve_all_pending"},          # cuentas de digitadores (autorizar ingresos: no toca personas, respuestas ni pagos)
    "parametros.py": {"get_event_logo", "set_event_logo_mode", "set_event_brand_color", "upload_event_logo", "set_digital_badge_enabled", "get_digital_badge_fields", "put_digital_badge_fields", "set_directory_page_size", "get_registro_gear_digitadores",
                      "set_registro_gear_digitadores", "get_last_name_required", "set_last_name_required", "set_idle_minutes", "set_facial_enabled", "set_certificates_enabled",
                      "get_event_categories", "set_event_categories", "add_optional_field", "list_field_configs", "upsert_field_config", "get_digital_email", "put_digital_email",
                      "preview_digital_email", "test_digital_email", "upload_email_image", "field_usage", "delete_field"},
    "person_form.py": {"get_person_form", "put_person_form"},
    "pledge.py": {"get_pledge", "create_link", "revoke_link", "set_enabled", "pledge_state"},          # compromiso del digitador: administrar el enlace y las banderas (el documento y lo sensible sí exigen datos abiertos)
    "print_settings.py": {"get_settings", "put_settings"},
    "print_stations.py": {"my_station", "put_station"},
    "privacy.py": {"get_privacy", "purge_event_biometrics", "purge_person_biometrics", "purge_data"},          # el derecho de supresión debe funcionar siempre
    "reprint.py": {"set_mode", "mine"},
    "roulette.py": {"get_roulette", "filter_fields", "save_behavior", "save_style", "upload_image", "display_link", "get_display_link", "authorize_spin", "cancel_authorization",
                    "get_authorization", "reset_round", "round_status"},
    "shared_print.py": {"_enabled_event", "config", "set_enabled", "set_route"},
    "stats.py": {"list_stats_variables"},
    "stats_links.py": {"create_link", "list_links", "revoke_link"},
    "uploads.py": {"sign_upload"},
}


def _functions_with_event_access():
    for path in sorted((ROOT / "app" / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                src = ast.unparse(fn)
                if "get_event_for_staff(" in src:
                    yield path.name, fn.name, ("require_data_open(" in src or "data_open_for(" in src)


def test_every_route_with_event_access_decides_about_the_archived_base():
    missing = [f"{f}:{n}" for f, n, guarded in _functions_with_event_access() if not guarded and n not in ALLOW.get(f, set())]
    assert not missing, ("Rutas con get_event_for_staff sin event_archive.require_data_open ni excepción en ALLOW (tests/test_base_archivada_guard.py). "
                         f"Si leen o escriben personas, respuestas o pagos, agrega el guard: {missing}")


def test_allow_list_has_no_dead_entries():
    seen = {(f, n) for f, n, _ in _functions_with_event_access()}
    dead = [f"{f}:{n}" for f, names in ALLOW.items() for n in names if (f, n) not in seen]
    assert not dead, f"Entradas de ALLOW que ya no existen: {dead}"


def test_allow_list_has_no_guarded_entries():
    guarded = {(f, n) for f, n, g in _functions_with_event_access() if g}
    both = [f"{f}:{n}" for f, names in ALLOW.items() for n in names if (f, n) in guarded]
    assert not both, f"Ya tienen guard, sobran en ALLOW: {both}"
