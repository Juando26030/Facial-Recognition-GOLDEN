-- Pruebas de esquema de la etapa C1c–C4 (corren entre la subida y la reversa). Cada una imprime OK o FALLA.
\set ON_ERROR_STOP off
INSERT INTO staff_users (username) VALUES ('u1');
INSERT INTO tenants (id, client_code, name) VALUES ('t1', 'AAAA1111', 'Empresa Uno');
INSERT INTO crm_accounts (code, name, name_norm) VALUES (1001, 'Cuenta Uno', 'cuenta uno');
INSERT INTO crm_contacts (account_id, first_name) VALUES (1, 'Ana');
SELECT CASE WHEN (SELECT count(*) FROM crm_pipelines WHERE is_default) = 1 AND (SELECT count(*) FROM crm_stages) = 7 THEN 'OK  embudo y 7 etapas sembrados' ELSE 'FALLA siembra' END;
SELECT CASE WHEN (SELECT count(*) FROM crm_stages WHERE kind='won') = 1 AND (SELECT count(*) FROM crm_stages WHERE kind='lost') = 1 THEN 'OK  una etapa ganada y una perdida' ELSE 'FALLA etapas cierre' END;
INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name) VALUES (5001, 1, 1, 1, 'Feria 2027');
SELECT CASE WHEN (SELECT outcome FROM crm_opportunities WHERE code=5001)='open' AND (SELECT currency FROM crm_opportunities WHERE code=5001)='COP' THEN 'OK  valores por defecto de la oportunidad' ELSE 'FALLA defectos' END;
DO $$ BEGIN
  BEGIN INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name) VALUES (5001, 1, 1, 1, 'Repetida'); RAISE NOTICE 'FALLA código repetido aceptado';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'OK  el código de oportunidad es único'; END;
  BEGIN DELETE FROM crm_stages WHERE id = 1; RAISE NOTICE 'FALLA se borró una etapa con oportunidades';
  EXCEPTION WHEN foreign_key_violation THEN RAISE NOTICE 'OK  no se borra una etapa con oportunidades (RESTRICT)'; END;
END $$;
INSERT INTO crm_activities (kind, subject, contact_id, opportunity_id) VALUES ('call', 'Llamar', 1, 1);
INSERT INTO crm_leads (first_name, status) VALUES ('Luis', 'nuevo');
INSERT INTO crm_activities (kind, subject, lead_id) VALUES ('note', 'Nota del lead', 1);
DELETE FROM crm_contacts WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_activities WHERE contact_id IS NULL AND subject='Llamar') = 0 AND (SELECT count(*) FROM crm_activities WHERE subject='Llamar')=0 THEN 'OK  al borrar un contacto se van sus actividades' ELSE 'FALLA cascada contacto→actividades' END;
DELETE FROM crm_leads WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_activities WHERE subject='Nota del lead') = 0 THEN 'OK  al borrar un lead se van sus actividades' ELSE 'FALLA cascada lead→actividades' END;
DELETE FROM crm_accounts WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_opportunities) = 0 THEN 'OK  al borrar una cuenta se van sus oportunidades' ELSE 'FALLA cascada cuenta→oportunidades' END;
DO $$ BEGIN
  INSERT INTO crm_accounts (code, name, name_norm) VALUES (1002, 'Cuenta Dos', 'cuenta dos');
  INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name, legacy_sugar_id) VALUES (5002, 2, 1, 1, 'A', 'abc');
  BEGIN INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name, legacy_sugar_id) VALUES (5003, 2, 1, 1, 'B', 'abc'); RAISE NOTICE 'FALLA legacy repetido aceptado';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'OK  el id de SuiteCRM no se repite (índice parcial)'; END;
  INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name) VALUES (5004, 2, 1, 1, 'C');
  INSERT INTO crm_opportunities (code, account_id, pipeline_id, stage_id, name) VALUES (5005, 2, 1, 1, 'D');
  RAISE NOTICE 'OK  varias oportunidades sin id de SuiteCRM conviven (NULL no choca)';
END $$;
INSERT INTO crm_import_runs (kind, mode) VALUES ('suitecrm', 'sample');
INSERT INTO crm_import_pairs (run_id, tenant_id, bucket) VALUES (1, 't1', 'seguro');
DELETE FROM crm_import_runs WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_import_pairs) = 0 THEN 'OK  al borrar una corrida se va su informe' ELSE 'FALLA cascada corrida→parejas' END;
SELECT CASE WHEN (SELECT status FROM crm_import_runs WHERE false) IS NULL THEN 'OK  fin de las pruebas de esquema' END;
