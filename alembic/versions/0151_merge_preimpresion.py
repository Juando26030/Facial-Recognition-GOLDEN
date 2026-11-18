"""Une las dos cabezas de staging: Almacén P2 (0149) y Preimpresiones (0150). No cambia el esquema.

Revision ID: 0151_merge_preimpresion
Revises: 0149_almacen_movimientos, 0150_print_logs_kind
"""
revision = "0151_merge_preimpresion"
down_revision = ("0149_almacen_movimientos", "0150_print_logs_kind")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
