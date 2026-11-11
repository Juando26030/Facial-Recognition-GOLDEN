"""Fase 10 B, pruebas «de texto» (leen el código fuente; corren sin base ni dependencias): cuentas de cobro abiertas y gastos con estado de conexiones."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_migration_0124_is_additive_reversible_and_neon_safe():
    s = _read("alembic/versions/0124_payment_acct_scope.py")
    assert 'revision = "0124_payment_acct_scope"' in s and len("0124_payment_acct_scope") <= 32
    for col in ("scope", "event_id", "form_id", "panelist_ref"):
        assert f'"{col}"' in s and s.count(f'"{col}"') >= 2          # se agrega y se quita
    assert 'server_default="general"' in s                           # lo existente queda «general»: nada cambia
    assert "drop_column" in s and "drop_table" not in s              # la bajada no toca cuentas ni llaves
    assert not re.search(r"\bSET\s+(SESSION|LOCAL)\b|advisory", s, re.I)


def test_no_account_is_created_automatically():
    """Una cuenta de cobro solo nace de POST /payment-accounts (el botón «Agregar cuenta de cobro»): ningún otro código la crea."""
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py") if re.search(r"(?<!class )PaymentAccount\(", p.read_text(encoding="utf-8"))]
    assert hits == ["app/routers/payment_accounts.py"], hits


def test_scope_columns_and_rules_exist():
    models = _read("app/models.py")
    block = models[models.index("class PaymentAccount"):models.index("class FormPayment")]
    for col in ("scope", "event_id", "form_id", "panelist_ref"):
        assert re.search(rf"\n    {col} = Column", block)
    assert "ForeignKey('web_forms.id'" not in block                      # sin ciclo de llaves con web_forms
    pa = _read("app/payment_accounts.py")
    assert 'SCOPES = {"general"' in pa and "def clean_scope" in pa and "def usable_for_form" in pa
    forms = _read("app/routers/forms.py")
    assert "payment_accounts.usable_for_form(acc, form)" in forms         # la asignación a un formulario respeta el alcance


def test_encrypted_keys_and_per_account_webhook_untouched():
    pa = _read("app/payment_accounts.py")
    assert "def cfg_for_payment" in pa and "for_new_charges=False" in pa and 'PREFIX = "pk1:"' in pa
    assert "/webhooks/wompi/{acc.ref}" in pa
    api = _read("app/routers/payment_accounts.py")
    assert "ADMIN = require_role(\"admin\")" in api                       # las llaves siguen siendo solo de admin/super_admin
    assert "scope" in _read("app/payment_accounts.py").split("def serialize")[1]


def test_cuentas_page_has_open_add_button_and_scope_picker():
    html = _read("templates/cuentas_cobro.html")
    assert "Agregar cuenta de cobro" in html and "data-new" in html
    js = _read("static/js/cuentas-cobro-page.js")
    assert "data-scope" in js and "panelist_ref" in js and "data-owner" in js
    assert "onclick" not in js and "alert(" not in js


def test_gastos_always_shows_connections_panel():
    html = _read("templates/gastos.html")
    assert 'id="gxConn"' in html and 'data-act="upload"' in html
    assert "{% if is_admin %}" in html                                    # la pestaña «Eventos» solo para admin
    js = _read("static/js/gastos-infra.js")
    assert "/api/gastos/infra/status" in js and "/api/gastos/infra/import/csv" in js and "Cómo conectarlo" in js
    assert "loadStatus()" in js and "No se pudo cargar los gastos" in js


def test_gastos_roles_admin_and_contabilidad():
    r = _read("app/routers/gastos.py")
    assert 'require_platform_role_or_any("admin", ("contabilidad",))' in r
    assert "/gastos/infra/status" in r and "/gastos/infra/import/csv" in r and "_need_table(db)" in r
    assert "def require_platform_role_or_any" in _read("app/auth.py")
    main = _read("app/main.py")
    page = main[main.index('@app.get("/gastos")'):main.index('@app.get("/cuentas-de-cobro")')]
    assert '"contabilidad" not in roles' in page and "is_admin" in page
    side = _read("templates/_sidebar.html")
    assert '{% if staff_role in ["admin", "super_admin", "contabilidad"] %}<a href="/gastos"' in side


def test_deploy_passes_infra_variables_to_web_and_ops():
    wf = _read(".github/workflows/cloudrun-deploy.yml")
    assert "GCP_BILLING_EXPORT_TABLE: ${{ vars.GCP_BILLING_EXPORT_TABLE }}" in wf and "ONEDRIVE_DRIVE_ID: ${{ vars.ONEDRIVE_DRIVE_ID }}" in wf
    sh = _read("deploy/gcp/deploy.sh")
    web = [ln for ln in sh.splitlines() if ln.startswith('deploy_service web ')][0]
    assert 'GCP_BILLING_EXPORT_TABLE=$GCP_BILLING_EXPORT_TABLE' in web
    ops = [ln for ln in sh.splitlines() if 'ops.yaml' in ln and 'env_file' in ln][0]
    assert 'GCP_BILLING_EXPORT_TABLE=$GCP_BILLING_EXPORT_TABLE' in ops and 'ONEDRIVE_DRIVE_ID=$ONEDRIVE_DRIVE_ID' in ops


def test_connections_never_print_values():
    s = _read("app/infra_costs.py")
    body = s[s.index("def connections"):s.index("_COL = {")]
    assert "{raw" not in body and "{os.getenv" not in body          # solo nombres de variables, nunca sus valores


def test_cuentas_modal_opens():
    """El cuadro de «Agregar cuenta de cobro» necesita data-open (sin él el CSS lo deja oculto y el botón parecía no hacer nada)."""
    assert "setAttribute('data-open', 'true')" in _read("static/js/cuentas-cobro-page.js")
