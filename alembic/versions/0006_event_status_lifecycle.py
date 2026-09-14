"""Event.status pasa de activo/cerrado a un ciclo de 3 pasos: creado -> en_proceso -> finalizado.
'creado' = recién creado, todavía no empezó (nadie puede registrar). 'en_proceso' lo activa
manualmente un coordinador+ cuando el evento arranca de verdad (es cuando digitador/cliente
pueden entrar). 'finalizado' lo cierra. Migración de datos, no de esquema (status sigue siendo
String) -- solo traduce los valores existentes.

Revision ID: 0006_event_status_lifecycle
Revises: 0005_event_dates_only
Create Date: 2026-09-18
"""
from alembic import op

revision = "0006_event_status_lifecycle"
down_revision = "0005_event_dates_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE events SET status = 'en_proceso' WHERE status = 'activo'")
    op.execute("UPDATE events SET status = 'finalizado' WHERE status = 'cerrado'")
    op.execute("ALTER TABLE events ALTER COLUMN status SET DEFAULT 'creado'")


def downgrade() -> None:
    op.execute("UPDATE events SET status = 'activo' WHERE status = 'en_proceso'")
    op.execute("UPDATE events SET status = 'cerrado' WHERE status = 'finalizado'")
    op.execute("ALTER TABLE events ALTER COLUMN status SET DEFAULT 'activo'")
