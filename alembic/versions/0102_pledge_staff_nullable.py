"""El compromiso firmado sobrevive a la eliminación de la cuenta (decisión de Juan David, 8-nov-2026).

Antes `event_staff_pledges.staff_id` era NOT NULL sin ON DELETE: una cuenta con compromiso firmado no se podía borrar (solo archivar). Ahora, al ELIMINAR los usuarios temporales de un
evento, la cuenta se borra y su evidencia (huella, firma, versión del texto, documento) queda en el evento SIN la cuenta (staff_id = NULL). Sigue valiendo la retención de lo sensible (30 días).

Revision ID: 0102_pledge_staff_nullable
Revises: 0101_event_staff_pledge
"""
from alembic import op

revision = "0102_pledge_staff_nullable"
down_revision = "0101_event_staff_pledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE event_staff_pledges ALTER COLUMN staff_id DROP NOT NULL")
    op.execute("ALTER TABLE event_staff_pledges DROP CONSTRAINT IF EXISTS event_staff_pledges_staff_id_fkey")
    op.execute("ALTER TABLE event_staff_pledges ADD CONSTRAINT event_staff_pledges_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_users(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("DELETE FROM event_staff_pledges WHERE staff_id IS NULL")
    op.execute("ALTER TABLE event_staff_pledges DROP CONSTRAINT IF EXISTS event_staff_pledges_staff_id_fkey")
    op.execute("ALTER TABLE event_staff_pledges ADD CONSTRAINT event_staff_pledges_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_users(id)")
    op.execute("ALTER TABLE event_staff_pledges ALTER COLUMN staff_id SET NOT NULL")
