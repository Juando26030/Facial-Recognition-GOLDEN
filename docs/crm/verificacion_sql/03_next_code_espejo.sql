-- Espejo en plpgsql de app/crm/codes.py (next_code y bump_floor), para probar la lógica y la concurrencia con psql cuando no hay Python con SQLAlchemy.
CREATE OR REPLACE FUNCTION crm_next_code(p_name text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v bigint; i int := 0;
BEGIN
  LOOP
    i := i + 1;
    IF i > 1000 THEN RAISE EXCEPTION 'sin numero libre'; END IF;
    UPDATE crm_counters SET value = value + 1, updated_at = now() WHERE name = p_name AND ready RETURNING value INTO v;
    IF NOT FOUND THEN RAISE EXCEPTION 'CodeCounterNotReady: %', p_name; END IF;
    IF p_name = 'account' THEN
      IF NOT EXISTS (SELECT 1 FROM tenants WHERE client_code = v::text OR legacy_client_code = v::text) AND NOT EXISTS (SELECT 1 FROM crm_accounts WHERE code = v) THEN RETURN v; END IF;
    ELSE
      IF NOT EXISTS (SELECT 1 FROM events WHERE lower(btrim(event_code)) = v::text) THEN RETURN v; END IF;
    END IF;
  END LOOP;
END $$;
CREATE OR REPLACE FUNCTION crm_bump_floor(p_name text, p_floor bigint) RETURNS bigint LANGUAGE sql AS $$
  INSERT INTO crm_counters (name, value, ready, updated_at) VALUES (p_name, p_floor, true, now())
  ON CONFLICT (name) DO UPDATE SET value = GREATEST(crm_counters.value, EXCLUDED.value), ready = true, updated_at = EXCLUDED.updated_at RETURNING value;
$$;
