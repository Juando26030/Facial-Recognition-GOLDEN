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
-- ---- 0133 (C3) ----
SELECT CASE WHEN (SELECT count(*) FROM crm_counters WHERE name IN ('quote','proforma') AND NOT ready AND value = 0) = 2 THEN 'OK  contadores quote y proforma nacen NO listos' ELSE 'FALLA contadores C3' END;
INSERT INTO crm_products (name, name_norm, sku) VALUES ('Escarapelas', 'escarapelas', 'ESC-1');
INSERT INTO crm_quotes (number, account_id, title) VALUES (9001, 2, 'Cotización de prueba');
INSERT INTO crm_quote_lines (quote_id, name, product_id) VALUES (1, 'Línea 1', 1);
DO $$ BEGIN
  BEGIN INSERT INTO crm_quotes (number, version, account_id, title) VALUES (9001, 1, 2, 'Repetida'); RAISE NOTICE 'FALLA número+versión repetidos aceptados';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'OK  número y versión de cotización no se repiten'; END;
  INSERT INTO crm_quotes (number, version, account_id, title, parent_quote_id) VALUES (9001, 2, 2, 'Versión 2', 1);
  RAISE NOTICE 'OK  una versión nueva repite el número';
  BEGIN INSERT INTO crm_products (name, name_norm, sku) VALUES ('Otro', 'otro', 'ESC-1'); RAISE NOTICE 'FALLA sku repetido aceptado';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'OK  el sku no se repite (índice parcial)'; END;
END $$;
INSERT INTO crm_contacts (account_id, first_name) VALUES (2, 'Beto');
UPDATE crm_quotes SET contact_id = (SELECT max(id) FROM crm_contacts) WHERE id = 1;
DELETE FROM crm_contacts WHERE id = (SELECT max(id) FROM crm_contacts);
SELECT CASE WHEN (SELECT contact_id FROM crm_quotes WHERE id = 1) IS NULL THEN 'OK  al suprimir un contacto su cotización queda sin contacto (SET NULL)' ELSE 'FALLA contacto→cotización' END;
DELETE FROM crm_products WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_quote_lines WHERE product_id IS NULL) = 1 THEN 'OK  borrar un producto deja la línea (SET NULL)' ELSE 'FALLA producto→línea' END;
INSERT INTO crm_proformas (number, quote_id, account_id, issued_at) VALUES (7001, 1, 2, current_date);
DELETE FROM crm_quotes WHERE id = 2;
DELETE FROM crm_quotes WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_quote_lines) = 0 AND (SELECT quote_id FROM crm_proformas WHERE number = 7001) IS NULL THEN 'OK  borrar la cotización borra sus líneas y deja la proforma' ELSE 'FALLA cascada cotización' END;
INSERT INTO crm_doc_templates (kind, name, is_default) VALUES ('quote', 'A', true);
DO $$ BEGIN
  BEGIN INSERT INTO crm_doc_templates (kind, name, is_default) VALUES ('quote', 'B', true); RAISE NOTICE 'FALLA dos plantillas predeterminadas';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'OK  una sola plantilla predeterminada por tipo'; END;
END $$;
INSERT INTO crm_saved_filters (owner_staff_id, scope, name, filters_json) VALUES (1, 'cuentas', 'Activas', '{"status":"activo"}');
DELETE FROM staff_users WHERE id = 1;
SELECT CASE WHEN (SELECT count(*) FROM crm_saved_filters) = 0 THEN 'OK  al borrar un usuario se van sus filtros guardados' ELSE 'FALLA cascada filtros' END;
SELECT CASE WHEN (SELECT status FROM crm_import_runs WHERE false) IS NULL THEN 'OK  fin de las pruebas de esquema' END;
