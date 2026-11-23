"""Tercer origen de la foto: «cada quien acepta» (formulario o QR). Solo ADITIVA.

  events.each_accepts   FALSE por defecto. TRUE = cada persona acepta por su cuenta (formulario, QR o enlace) y en la puerta el escáner NO pide cédula: sale «Acepto», se abre la cámara y solo se reconoce
                        a quienes ya tienen su aceptación registrada. No exige anexo (no hay fotos entregadas por el cliente).

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0165_each_accepts
Revises: 0164_accept_verify_photo
"""
import sqlalchemy as sa
from alembic import op

revision = "0165_each_accepts"
down_revision = "0164_accept_verify_photo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("each_accepts", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("events", "each_accepts")
