"""Plantilla de evento (Fase 2, entrega 2). Solo ADITIVA.

  event_templates          la plantilla (una por ámbito; hoy 'global'): campos, vista de creación y vista del calendario, con `version` para el bloqueo optimista
  event_template_revisions historial de guardados (quién, cuándo y cómo quedó)
  events.extra_json        valores de los campos personalizados de la plantilla {clave: valor}; los campos base y los interruptores siguen en sus columnas

NO migra datos de eventos existentes (decisión de Juan David: primero la plantilla, después la migración). Sin fila en event_templates la aplicación usa la plantilla de fábrica, que reproduce el
formulario «Nuevo evento» de siempre. Permisos: si existe el rol `golden_app`, se le dan los de las dos tablas nuevas y sus secuencias (como 0084). Sin SET de sesión ni advisory locks; compatible con el pooler de Neon. El código anterior ignora la columna y las tablas. Bajar la migración las quita.

Revision ID: 0087_event_templates
Revises: 0086_digitador_login_control
Create Date: 2026-11-07
"""
from alembic import op

revision = "0087_event_templates"
down_revision = "0086_digitador_login_control"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_templates (
            id SERIAL PRIMARY KEY,
            scope VARCHAR NOT NULL,
            tenant_id VARCHAR NULL REFERENCES tenants(id),
            fields_json TEXT NOT NULL,
            creation_layout_json TEXT NOT NULL,
            calendar_layout_json TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP NOT NULL,
            updated_by_id INTEGER NULL REFERENCES staff_users(id),
            CONSTRAINT uq_event_templates_scope UNIQUE (scope)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_template_revisions (
            id SERIAL PRIMARY KEY,
            template_id INTEGER NOT NULL REFERENCES event_templates(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            saved_by_id INTEGER NULL REFERENCES staff_users(id),
            saved_at TIMESTAMP NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_template_revisions_template_id ON event_template_revisions (template_id)")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS extra_json TEXT NULL")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'golden_app') THEN "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON event_templates, event_template_revisions TO golden_app; "
               "GRANT USAGE, SELECT, UPDATE ON SEQUENCE event_templates_id_seq, event_template_revisions_id_seq TO golden_app; END IF; END $$")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS extra_json")
    op.execute("DROP TABLE IF EXISTS event_template_revisions")
    op.execute("DROP TABLE IF EXISTS event_templates")
