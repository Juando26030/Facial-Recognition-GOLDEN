"""Puestos de impresión configurados desde Parámetros y política de sesiones por rol (26-oct-2026). Solo ADITIVA: tablas nuevas y dos columnas de `staff_users` con valor por
defecto; no toca ni reescribe ningún dato existente. El código anterior (b225a2d) ignora lo nuevo. Sin fila en `print_stations` el puesto usa lo de siempre, y una cuenta sin
`session_token` (sesión creada antes del cambio) sigue válida hasta que vuelva a iniciar sesión.

  print_stations   configuración de impresión de UNA cuenta de puesto en UN evento (JSON), guardada en el servidor
  staff_users.print_station   casilla «Puesto de impresión» (cuenta protegida: un segundo inicio de sesión se rechaza)
  staff_users.session_token   identificador de la sesión vigente de la cuenta (NULL = sin sesión única registrada)
  app_settings     clave/valor (interruptor «Sesión única»)
  session_audit    sesiones cerradas, rechazadas o forzadas: cuenta, hora, tipo de dispositivo, navegador y resultado. Se conserva 90 días (Ley 1581): lo borra el Job de operaciones.

Revision ID: 0072_puestos_sesiones
Revises: 0071_print_job_prefs
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0072_puestos_sesiones"
down_revision = "0071_print_job_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_stations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "staff_user_id", name="uq_print_station_event_staff"),
    )
    op.add_column("staff_users", sa.Column("print_station", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("staff_users", sa.Column("session_token", sa.String(40), nullable=True))
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "session_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("staff_user_id", sa.Integer(), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("device", sa.String(20), nullable=True),
        sa.Column("browser", sa.String(40), nullable=True),
        sa.Column("result", sa.String(20), nullable=False),
    )
    op.create_index("ix_session_audit_created_at", "session_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_session_audit_created_at", table_name="session_audit")
    op.drop_table("session_audit")
    op.drop_table("app_settings")
    op.drop_column("staff_users", "session_token")
    op.drop_column("staff_users", "print_station")
    op.drop_table("print_stations")
