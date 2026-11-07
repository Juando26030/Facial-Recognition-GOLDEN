"""Control del ingreso de los digitadores y época de sesión. Solo ADITIVA.

  staff_users.failed_logins     intentos fallidos seguidos de una cuenta digitador (3 = bloqueada; un ingreso correcto lo vuelve a 0)
  staff_users.locked_at         cuándo quedó bloqueada (NULL = no bloqueada); la desbloquea quien administra las cuentas temporales del evento
  staff_users.login_req_hash    SHA-256 del token de la solicitud de ingreso pendiente (el token en claro solo vive en la cookie firmada del navegador que la hizo)
  staff_users.login_req_at      cuándo se pidió (vence a los 5 minutos)
  staff_users.login_req_status  pending | approved | denied (NULL = ninguna)
  staff_users.session_epoch     época de sesión de la cuenta: al cambiar o restablecer la contraseña sube y toda cookie con otra época deja de valer

Sin SET de sesión, sin advisory locks; compatible con el pooler de Neon. El código anterior ignora las columnas. Bajar la migración las quita.

Revision ID: 0086_digitador_login_control
Revises: 0085_tours_auto_off
Create Date: 2026-11-06
"""
from alembic import op

revision = "0086_digitador_login_control"
down_revision = "0085_tours_auto_off"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("failed_logins", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_at", "TIMESTAMP NULL"),
    ("login_req_hash", "VARCHAR(64) NULL"),
    ("login_req_at", "TIMESTAMP NULL"),
    ("login_req_status", "VARCHAR(12) NULL"),
    ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
)


def upgrade() -> None:
    for name, ddl in _COLUMNS:
        op.execute(f"ALTER TABLE staff_users ADD COLUMN IF NOT EXISTS {name} {ddl}")


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE staff_users DROP COLUMN IF EXISTS {name}")
