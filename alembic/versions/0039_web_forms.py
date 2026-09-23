"""Sprint 5: Formularios Web (formularios de inscripción propios de un evento).

Revision ID: 0039_web_forms
Revises: 0038_roulette
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0039_web_forms"
down_revision = "0038_roulette"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_forms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("manual_status", sa.String(), nullable=False),
        sa.Column("use_schedule", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schedule_json", sa.Text(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("design_json", sa.Text(), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=True),
        sa.Column("test_key", sa.String(), nullable=False),
        sa.Column("fed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("staff_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", "slug", name="uq_web_form_event_slug"),
    )
    op.create_table(
        "form_invites",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token", name="uq_form_invite_token"),
        sa.UniqueConstraint("form_id", "person_id", name="uq_form_invite_person"),
    )
    op.create_table(
        "form_submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("person_id", sa.String(), nullable=True),
        sa.Column("invite_id", sa.Integer(), sa.ForeignKey("form_invites.id"), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("sid", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("fed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_form_submissions_form", "form_submissions", ["form_id", "is_test"])
    op.create_table(
        "form_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("sid", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_form_events_form", "form_events", ["form_id", "kind"])
    op.create_table(
        "form_people",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.Integer(), sa.ForeignKey("web_forms.id"), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("form_id", "person_id", name="uq_form_person"),
    )
    op.create_table(
        "saved_form_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("design_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("saved_form_templates")
    op.drop_table("form_people")
    op.drop_index("ix_form_events_form", table_name="form_events")
    op.drop_table("form_events")
    op.drop_index("ix_form_submissions_form", table_name="form_submissions")
    op.drop_table("form_submissions")
    op.drop_table("form_invites")
    op.drop_table("web_forms")
