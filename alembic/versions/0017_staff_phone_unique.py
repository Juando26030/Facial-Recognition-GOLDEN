"""Sprint 2.4 Fase 4 (2026-09-16): StaffUser.phone pasa a ser llave única — pedido explícito ("no
puede haber dos usuarios con el mismo teléfono"). Antes de crear la restricción, se limpian en la
propia base los casos que ya existan: cadenas vacías se normalizan a NULL, y si dos o más cuentas
comparten el mismo número, se conserva el de la cuenta más antigua (menor id) y se vacía el resto
(no se puede adivinar cuál es el correcto sin preguntar, y un teléfono NULL sigue permitiendo que
el usuario funcione con normalidad — es opcional para cliente/digitador y se puede volver a
completar a mano para las demás cuentas). Un UNIQUE estándar no choca entre múltiples NULL, tanto
en Postgres como en SQLite, así que no hace falta un índice parcial aparte.

Revision ID: 0017_staff_phone_unique
Revises: 0016_print_logs
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_staff_phone_unique"
down_revision = "0016_print_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("UPDATE staff_users SET phone = NULL WHERE phone = ''"))

    duplicated_phones = conn.execute(sa.text(
        "SELECT phone FROM staff_users WHERE phone IS NOT NULL GROUP BY phone HAVING COUNT(*) > 1"
    )).fetchall()
    for (phone,) in duplicated_phones:
        rows = conn.execute(sa.text(
            "SELECT id FROM staff_users WHERE phone = :phone ORDER BY id"
        ), {"phone": phone}).fetchall()
        keep_id = rows[0][0]
        other_ids = [r[0] for r in rows[1:]]
        conn.execute(
            sa.text("UPDATE staff_users SET phone = NULL WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": other_ids},
        )

    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.create_unique_constraint("uq_staff_users_phone", ["phone"])


def downgrade() -> None:
    with op.batch_alter_table("staff_users") as batch_op:
        batch_op.drop_constraint("uq_staff_users_phone", type_="unique")
