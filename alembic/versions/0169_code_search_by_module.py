"""Cómo se busca a la persona, POR PANTALLA (Parámetros › Campos › Código de la persona; 26-nov-2026, Juan David). Solo ADITIVA.

  events.code_search_registro    'id_first' | 'code_first' | 'code_only' | 'id_only'   (Registro)
  events.code_search_inventario  igual                                                 (Control de inventario)
  events.code_search_zonas       igual                                                 (Control de zonas)

  id_first   = primero la cédula y luego el código (lo de siempre)
  code_first = primero el código y luego la cédula (antes «Dar prioridad al código», 0166)
  code_only  = solo por código (antes «Solo buscar por código», 0168)
  id_only    = solo por cédula (nuevo)

Por qué: en un evento el código se ASIGNA en Registro (se busca por cédula) y luego Inventario y Zonas buscan solo por código; con una sola opción
para todo el evento no se podía. Se copia lo que cada evento ya tenía (0166/0168) a las tres pantallas, así nada cambia al desplegar.
Las columnas viejas `code_search_first` / `code_search_only` se dejan (aditiva) pero ya no se leen. Solo tiene efecto con `code_enabled`.

Escrita a mano; sin SET de sesión (pooler de Neon). Id ≤ 32 caracteres.

Revision ID: 0169_code_search_by_module
Revises: 0168_code_search_only
"""
import sqlalchemy as sa
from alembic import op

revision = "0169_code_search_by_module"
down_revision = "0168_code_search_only"
branch_labels = None
depends_on = None

COLUMNS = ("code_search_registro", "code_search_inventario", "code_search_zonas")


def upgrade():
    for name in COLUMNS:
        op.add_column("events", sa.Column(name, sa.String(length=12), nullable=False, server_default="id_first"))
    for name in COLUMNS:
        op.execute(f"UPDATE events SET {name} = CASE WHEN code_search_only THEN 'code_only' WHEN code_search_first THEN 'code_first' ELSE 'id_first' END")


def downgrade():
    for name in COLUMNS:
        op.drop_column("events", name)
