"""Reserva de cupo de un formulario en UNA sola sentencia SQL (Fase 1-2 de escalabilidad, doc 13 §11.4): antes,
`FOR UPDATE` bloqueaba la fila del formulario y LUEGO se hacían varias consultas más (cupo total, cupos por
variable, duplicado) mientras el bloqueo seguía activo — con más envíos simultáneos, más tiempo bloqueada la
fila. `form_reserve_slot()` hace TODO eso en una sola ida y vuelta a la base, con el bloqueo adentro de la
propia función.

No cubre los códigos de descuento (tabla aparte, conteo ya barato con una sola consulta) ni la purga de
inscripciones abandonadas (no necesita el bloqueo de la fila) — se documenta como decisión, no un olvido.

Revision ID: 0049_form_atomic_reserve
Revises: 0048_jobs_ops
Create Date: 2026-09-27
"""
from alembic import op

revision = "0049_form_atomic_reserve"
down_revision = "0048_jobs_ops"
branch_labels = None
depends_on = None

FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION form_reserve_slot(
    p_form_id integer,
    p_person_id text,
    p_is_test boolean,
    p_matched jsonb
) RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_capacity integer;
    v_hold_from timestamp;
    v_held integer;
    v_dup boolean;
    v_rule jsonb;
    v_used integer;
BEGIN
    -- Bloquea la fila del formulario: nadie más reserva mientras dura esta función (una sola ida y vuelta).
    SELECT capacity INTO v_capacity FROM web_forms WHERE id = p_form_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'not_found');
    END IF;

    IF p_is_test THEN
        RETURN jsonb_build_object('ok', true);   -- las inscripciones de prueba nunca cuentan ni se bloquean
    END IF;

    v_hold_from := now() - interval '30 minutes';

    IF v_capacity IS NOT NULL THEN
        SELECT count(*) INTO v_held FROM form_submissions
        WHERE form_id = p_form_id AND is_test = false
          AND (status = 'confirmed' OR (status = 'awaiting_payment' AND created_at > v_hold_from));
        IF v_held >= v_capacity THEN
            RETURN jsonb_build_object('ok', false, 'reason', 'capacity');
        END IF;
    END IF;

    IF p_person_id IS NOT NULL AND p_person_id <> '' THEN
        SELECT EXISTS(
            SELECT 1 FROM form_submissions
            WHERE form_id = p_form_id AND is_test = false AND status = 'confirmed' AND person_id = p_person_id
        ) INTO v_dup;
        IF v_dup THEN
            RETURN jsonb_build_object('ok', false, 'reason', 'duplicate');
        END IF;
    END IF;

    FOR v_rule IN SELECT * FROM jsonb_array_elements(coalesce(p_matched, '[]'::jsonb))
    LOOP
        SELECT count(*) INTO v_used FROM form_submissions
        WHERE form_id = p_form_id AND is_test = false
          AND (status = 'confirmed' OR (status = 'awaiting_payment' AND created_at > v_hold_from))
          AND position(('|' || (v_rule->>'sig') || '|') in coalesce(quota_keys, '')) > 0;
        IF v_used >= (v_rule->>'limit')::integer THEN
            RETURN jsonb_build_object('ok', false, 'reason', 'quota', 'label', v_rule->>'label');
        END IF;
    END LOOP;

    RETURN jsonb_build_object('ok', true);
END;
$$;
"""


def upgrade() -> None:
    op.execute(FUNCTION_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS form_reserve_slot(integer, text, boolean, jsonb);")
