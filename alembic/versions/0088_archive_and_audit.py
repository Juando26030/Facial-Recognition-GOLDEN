"""Fase 3, oleada 1 (clientes). Solo ADITIVA.

  tenants.archived_at / archived_by_id   archivar un cliente = ocultarlo de las listas (NULL = activo); se restaura; no se borra nada (contrato: poder desarchivar la base).
  audit_actions                          quién archivó, restauró o borró qué y cuándo (solo INSERT; sin datos personales)

Permisos: si existe el rol `golden_app`, se le dan los de la tabla nueva y su secuencia (como 0084 y 0087).

Revision ID: 0088_archive_and_audit
Revises: 0087_event_templates
Create Date: 2026-11-07
"""
from alembic import op

revision = "0088_archive_and_audit"
down_revision = "0087_event_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS archived_by_id INTEGER NULL REFERENCES staff_users(id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_actions (
            id SERIAL PRIMARY KEY,
            at TIMESTAMP NOT NULL,
            actor_id INTEGER NULL REFERENCES staff_users(id),
            actor_role VARCHAR(20) NULL,
            action VARCHAR(40) NOT NULL,
            entity VARCHAR(40) NOT NULL,
            entity_id VARCHAR(64) NOT NULL,
            entity_name VARCHAR(200) NULL,
            detail VARCHAR(500) NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_actions_entity ON audit_actions (entity, entity_id)")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN
                GRANT SELECT, INSERT ON audit_actions TO golden_app;
                GRANT USAGE, SELECT ON SEQUENCE audit_actions_id_seq TO golden_app;
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS audit_actions")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS archived_by_id")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS archived_at")
