"""Origen de carga de cada persona EN un evento, separado de su estado de registro (B1, 26-oct-2026). Solo ADITIVA: una columna de texto que admite NULL en `event_attendees`
(NULL = «Desconocido»); el código anterior (b225a2d) la ignora. Valores: «base» (Excel / carga masiva), «manual» (alta a mano), «autoregistro» (formulario web).

Relleno de los datos existentes con lo que haya, SIN tocar ninguna otra columna ni el estado:
  1. «manual»        si en ese evento hay un ingreso «Nuevo» de la persona (el alta manual deja ese rastro);
  2. «autoregistro»  si un formulario web del evento (no de prueba) alimentó a esa persona;
  3. «base»          si la inscripción se creó durante una carga masiva del evento (entre el inicio y el final de la tarea, con 2 minutos de holgura);
  4. lo demás queda NULL («Desconocido»): datos viejos sin rastro.
La bajada quita la columna (y con ella solo lo nuevo).

Revision ID: 0073_attendee_origin
Revises: 0072_puestos_sesiones
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0073_attendee_origin"
down_revision = "0072_puestos_sesiones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("event_attendees", sa.Column("origin", sa.String(16), nullable=True))
    op.execute("""
        UPDATE event_attendees ea SET origin = 'manual'
        WHERE ea.origin IS NULL AND EXISTS (SELECT 1 FROM access_logs l WHERE l.event_id = ea.event_id AND l.user_id = ea.user_id AND l.record_type = 'Nuevo')
    """)
    op.execute("""
        UPDATE event_attendees ea SET origin = 'autoregistro'
        WHERE ea.origin IS NULL AND EXISTS (SELECT 1 FROM form_submissions fs WHERE fs.event_id = ea.event_id AND fs.person_id = ea.user_id AND fs.fed AND NOT fs.is_test)
    """)
    op.execute("""
        UPDATE event_attendees ea SET origin = 'base'
        WHERE ea.origin IS NULL AND ea.created_at IS NOT NULL AND EXISTS (
            SELECT 1 FROM bulk_jobs bj WHERE bj.event_id = ea.event_id
              AND ea.created_at BETWEEN bj.created_at - interval '2 minutes' AND COALESCE(bj.finished_at, bj.updated_at, bj.created_at) + interval '2 minutes')
    """)


def downgrade() -> None:
    op.drop_column("event_attendees", "origin")
