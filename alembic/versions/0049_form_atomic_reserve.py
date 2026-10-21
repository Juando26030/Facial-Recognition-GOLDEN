"""Reserva de cupo de un formulario en UNA sola ida y vuelta a la base (doc 13 §15.2).

Antes, `FOR UPDATE` bloqueaba la fila del formulario y LUEGO se hacían 5-7 consultas más (reintento, cupos por variable, cupo
total, duplicado) con el bloqueo activo. Con la base a 10-15 ms (Cloud Run us-east1 → Neon us-east-1) eso limitaba cada
formulario a ~25 envíos/s. `form_reserve_slot()` hace todas esas verificaciones dentro de la base, con el bloqueo adentro.

Mismas reglas que `app/formsvc.py` (`held_count`, `quota_counts`, `real_submissions`). La hora de corte de la reserva de pago
llega desde Python (`PENDING_HOLD`, en UTC como `created_at`), así hay una sola definición y no depende de la zona horaria de la
sesión. Si hay inscripciones sin `quota_keys` (reglas recién editadas) devuelve `rebuild` y Python las recalcula y reintenta.

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
    p_sid text,
    p_is_test boolean,
    p_hold_from timestamp,
    p_matched jsonb
) RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_capacity integer;
    v_held integer;
    v_rule jsonb;
    v_used integer;
BEGIN
    -- Bloquea la fila del formulario hasta el final de la transaccion de quien llama (el INSERT va despues, en la misma).
    SELECT capacity INTO v_capacity FROM web_forms WHERE id = p_form_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'not_found');
    END IF;

    -- Reintento del navegador con la misma clave de envio: la inscripcion ya quedo confirmada.
    IF p_sid IS NOT NULL AND EXISTS (
        SELECT 1 FROM form_submissions
        WHERE form_id = p_form_id AND sid = p_sid AND is_test = p_is_test AND status = 'confirmed'
          AND (p_person_id IS NULL OR person_id = p_person_id)
    ) THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'retry');
    END IF;

    IF p_is_test THEN
        RETURN jsonb_build_object('ok', true);   -- las pruebas nunca cuentan para cupos ni duplicados
    END IF;

    IF jsonb_array_length(coalesce(p_matched, '[]'::jsonb)) > 0 AND EXISTS (
        SELECT 1 FROM form_submissions WHERE form_id = p_form_id AND quota_keys IS NULL
    ) THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'rebuild');
    END IF;

    FOR v_rule IN SELECT * FROM jsonb_array_elements(coalesce(p_matched, '[]'::jsonb))
    LOOP
        SELECT count(*) INTO v_used FROM form_submissions
        WHERE form_id = p_form_id AND is_test = false
          AND (status = 'confirmed' OR (status = 'awaiting_payment' AND created_at > p_hold_from))
          AND strpos(quota_keys, '|' || (v_rule->>'sig') || '|') > 0;
        IF v_used >= (v_rule->>'limit')::integer THEN
            RETURN jsonb_build_object('ok', false, 'reason', 'quota', 'label', v_rule->>'label');
        END IF;
    END LOOP;

    IF v_capacity IS NOT NULL THEN
        SELECT
            (SELECT count(*) FROM form_submissions
             WHERE form_id = p_form_id AND is_test = false AND status = 'confirmed')
          + (SELECT count(*) FROM form_payments
             WHERE form_id = p_form_id AND status = 'pending' AND is_test = false
               AND submission_id IS NOT NULL AND created_at > p_hold_from)
        INTO v_held;
        IF v_held >= v_capacity THEN
            RETURN jsonb_build_object('ok', false, 'reason', 'capacity');
        END IF;
    END IF;

    IF p_person_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM form_submissions
        WHERE form_id = p_form_id AND is_test = false AND status = 'confirmed' AND person_id = p_person_id
    ) THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'duplicate');
    END IF;

    RETURN jsonb_build_object('ok', true);
END;
$$;
"""


def upgrade() -> None:
    op.execute(FUNCTION_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS form_reserve_slot(integer, text, text, boolean, timestamp, jsonb);")
