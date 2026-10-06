"""Registro inmutable de consentimientos biométricos (`audit_consent_logs`): prueba de la autorización (art. 9 Ley 1581; Decreto 1074/2015, art. 2.2.2.25.2.6).

Solo INSERT: un disparador rechaza UPDATE, DELETE y TRUNCATE para cualquier rol, y además se le quitan esos privilegios al rol de la app (`golden_app`, si existe;
scripts/neon_app_role.py repite el REVOKE porque concede privilegios sobre todas las tablas). SIN llaves foráneas: ninguna supresión de personas, eventos o clientes
(ni cascada) la toca. Retención mínima de 3 años; ninguna purga la incluye.

Revision ID: 0054_audit_consent_logs
Revises: 0051_biometric_retention
Create Date: 2026-10-06
NOTA al integrar con `producto/estados-evento` (0052) y `producto/piloto` (0053): cambiar `down_revision` a la última de esas para dejar UNA sola cabeza.
"""
import sqlalchemy as sa
from alembic import op

revision = "0054_audit_consent_logs"
down_revision = "0053_directory_page_size"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_consent_logs",
        sa.Column("id", sa.String(36), primary_key=True),                     # lo genera el dispositivo (sin conexión): un reintento no duplica
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("user_id", sa.String, nullable=False),                      # misma llave que `users` (id + tenant_id), SIN llave foránea
        sa.Column("cedula_hash", sa.String(64), nullable=False),              # HMAC-SHA256 de la cédula: sirve para encontrar a la persona aunque su `users` ya no exista
        sa.Column("event_id", sa.Integer, nullable=False),                    # sin llave foránea
        sa.Column("consent_timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("legal_text_hash", sa.String(64), nullable=False),          # SHA-256 del texto EXACTO mostrado
        sa.Column("accepted_biometric", sa.Boolean, nullable=False),
        sa.Column("confirmed_adult", sa.Boolean, nullable=False),
        sa.Column("ip_or_device_id", sa.String, nullable=True),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.CheckConstraint("reason IN ('consent', 'rejection', 'revocation')", name="ck_audit_consent_reason"),
    )
    op.create_index("ix_audit_consent_person_event", "audit_consent_logs", ["tenant_id", "user_id", "event_id", "consent_timestamp_utc"])
    op.create_index("ix_audit_consent_cedula_hash", "audit_consent_logs", ["cedula_hash"])
    op.execute("""
        CREATE FUNCTION audit_consent_logs_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit_consent_logs es de solo inserción (%)', TG_OP USING ERRCODE = 'insufficient_privilege'; END $$""")
    op.execute("CREATE TRIGGER audit_consent_logs_no_update_delete BEFORE UPDATE OR DELETE ON audit_consent_logs FOR EACH ROW EXECUTE FUNCTION audit_consent_logs_append_only()")
    op.execute("CREATE TRIGGER audit_consent_logs_no_truncate BEFORE TRUNCATE ON audit_consent_logs FOR EACH STATEMENT EXECUTE FUNCTION audit_consent_logs_append_only()")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN "
               "REVOKE UPDATE, DELETE, TRUNCATE ON audit_consent_logs FROM golden_app; END IF; END $$")


def downgrade() -> None:      # solo para desarrollo: en producción esta tabla no se baja (es prueba legal)
    op.execute("DROP TABLE audit_consent_logs")
    op.execute("DROP FUNCTION audit_consent_logs_append_only()")
