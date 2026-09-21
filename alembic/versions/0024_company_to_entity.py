"""Reunión 2026-09-21, ítem 3b: "Empresa" pasa a llamarse "Entidad" en toda la app.

Renombra `users.company` -> `users.entity` y migra los datos que guardaban la clave vieja como
TEXTO (no como columna): `event_field_configs.field_key` y las variables de los elementos de
escarapela (`elements_json` de `badge_templates` y `saved_badge_templates`: `variable`, y las
`variables` de un QR). Sin esto, las escarapelas ya diseñadas imprimirían vacío en ese campo.

Revision ID: 0024_company_to_entity
Revises: 0023_access_log_reg_method
Create Date: 2026-09-21
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0024_company_to_entity"
down_revision = "0023_access_log_reg_method"
branch_labels = None
depends_on = None


def _swap(elements_json: str, old: str, new: str) -> str:
    try:
        elements = json.loads(elements_json or "[]")
    except ValueError:
        return elements_json
    for el in elements:
        if el.get("variable") == old:
            el["variable"] = new
        if isinstance(el.get("variables"), list):
            el["variables"] = [new if v == old else v for v in el["variables"]]
    return json.dumps(elements)


def _rename_key(old: str, new: str) -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE event_field_configs SET field_key = :new WHERE field_key = :old"), {"old": old, "new": new})
    for table in ("badge_templates", "saved_badge_templates"):
        for row_id, raw in conn.execute(sa.text(f"SELECT id, elements_json FROM {table}")).fetchall():
            fixed = _swap(raw, old, new)
            if fixed != raw:
                conn.execute(sa.text(f"UPDATE {table} SET elements_json = :j WHERE id = :i"), {"j": fixed, "i": row_id})


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("company", new_column_name="entity")
    _rename_key("company", "entity")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("entity", new_column_name="company")
    _rename_key("entity", "company")
