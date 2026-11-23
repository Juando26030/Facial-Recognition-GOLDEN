"""Verificar antes de reemplazar la foto de registro en /aceptar (revisión de seguridad 22-nov-2026, hallazgo 5). Solo ADITIVA.

  events.accept_verify_photo   TRUE (por defecto, también para los eventos que ya existen: es la opción segura) = la selfie de quien NO está verificada
                               no pisa la foto de registro existente: queda «pendiente» y la sustituye solo al verificarse la persona.
                               FALSE = la selfie reemplaza la foto de inmediato (como antes), por decisión del evento.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0164_accept_verify_photo
Revises: 0163_local_nodes_tenant
"""
from alembic import op

revision = "0164_accept_verify_photo"
down_revision = "0163_local_nodes_tenant"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS accept_verify_photo BOOLEAN NOT NULL DEFAULT TRUE")


def downgrade():
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS accept_verify_photo")
