-- Espejo en SQL de downgrade() de la migración 0130.
UPDATE tenants SET client_code = legacy_client_code WHERE legacy_client_code IS NOT NULL;
DROP TABLE crm_change_log;
DROP TABLE crm_notes;
DROP TABLE crm_contacts;
DROP TABLE crm_accounts;
DROP TABLE crm_counters;
ALTER TABLE tenants DROP CONSTRAINT uq_tenants_legacy_client_code;
ALTER TABLE tenants DROP COLUMN legacy_client_code;
