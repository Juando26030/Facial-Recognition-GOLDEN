"""Retención biométrica de 7 días tras finalizar (tope de 180 días desde la captura): hace falta saber CUÁNDO se finalizó cada evento
(`events.finalized_at`, se reinicia al reabrirlo) y CUÁNDO se capturó cada rostro (`users.face_captured_at`, para el tope).

Relleno de lo que ya existe (decisión documentada en docs/15): eventos ya finalizados → `finalized_at` = ahora (el reloj de 7 días empieza con esta
migración: nada se borra por sorpresa en la primera corrida); rostros ya guardados → `face_captured_at` = su constancia de autorización si la
hay, si no ahora (el tope de 180 días empieza a contar desde aquí para los que no tienen constancia).

Revision ID: 0051_biometric_retention
Revises: 0050_bulk_job_spec
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0051_biometric_retention"
down_revision = "0050_bulk_job_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("face_captured_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE events SET finalized_at = (now() AT TIME ZONE 'utc') WHERE status = 'finalizado'")
    op.execute("UPDATE users SET face_captured_at = COALESCE(biometric_consent_at, now() AT TIME ZONE 'utc') WHERE face_encoding IS NOT NULL AND face_encoding <> ''")
    op.create_index("ix_users_face_captured_at", "users", ["face_captured_at"])


def downgrade() -> None:
    op.drop_index("ix_users_face_captured_at", table_name="users")
    op.drop_column("users", "face_captured_at")
    op.drop_column("events", "finalized_at")
