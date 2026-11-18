"""Une las dos ramas de migraciones: 0149 (almacén: movimientos) y 0150 (preimpresiones: print_logs.kind). No cambia nada en la base.

La base de staging ya quedó marcada en esta revisión (18-nov-2026) por una unión local de estas dos ramas; esta es la misma unión, ahora versionada.

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
