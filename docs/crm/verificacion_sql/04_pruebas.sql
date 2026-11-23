\set ON_ERROR_STOP off
\echo === 1. contador NO listo: se niega
SELECT crm_next_code('account');
\echo === 2. bump_floor lo deja listo en 100; luego 3 números consecutivos (101,102,103)
SELECT crm_bump_floor('account', 100);
SELECT crm_next_code('account'), crm_next_code('account'), crm_next_code('account');
\echo === 3. bump_floor nunca baja (pide 50, queda en 103)
SELECT crm_bump_floor('account', 50);
\echo === 4. salta ocupados: hexadecimal de solo digitos, alias viejo y cuenta del CRM (104,105,106 ocupados -> debe dar 107)
INSERT INTO tenants (id, client_code, name) VALUES ('t104','104','a'), ('t105','AAAA1111','b');
UPDATE tenants SET legacy_client_code = '105' WHERE id = 't105';
INSERT INTO crm_accounts (code, name, name_norm) VALUES (106, 'x', 'x');
SELECT crm_next_code('account');
\echo === 5. sin huecos: un ROLLBACK no consume numero (siguiente debe ser 108 dos veces)
BEGIN; SELECT crm_next_code('account'); ROLLBACK;
SELECT crm_next_code('account');
\echo === 6. evento: no listo; con floor 10 y un evento con codigo numerico 11 -> da 12
SELECT crm_next_code('event');
SELECT crm_bump_floor('event', 10);
INSERT INTO tenants (id, client_code, name) VALUES ('t1','C1','n');
INSERT INTO events (tenant_id, event_code, name) VALUES ('t1',' 11 ','e');
SELECT crm_next_code('event');
\echo === 7. restricciones: cuenta duplicada por tenant_id, codigo repetido, dos contactos principales, legacy repetido (4 errores esperados)
INSERT INTO crm_accounts (code, tenant_id, name, name_norm) VALUES (200, 't1', 'a', 'a');
INSERT INTO crm_accounts (code, tenant_id, name, name_norm) VALUES (201, 't1', 'b', 'b');
INSERT INTO crm_accounts (code, name, name_norm) VALUES (200, 'c', 'c');
INSERT INTO crm_contacts (account_id, is_primary) SELECT id, true FROM crm_accounts WHERE code = 200;
INSERT INTO crm_contacts (account_id, is_primary) SELECT id, true FROM crm_accounts WHERE code = 200;
INSERT INTO crm_accounts (code, name, name_norm, legacy_sugar_id) VALUES (210, 'd', 'd', 'abc');
INSERT INTO crm_accounts (code, name, name_norm, legacy_sugar_id) VALUES (211, 'e', 'e', 'abc');
\echo === 8. cascada: borrar la cuenta 200 borra contactos y notas
INSERT INTO crm_notes (account_id, contact_id, body) SELECT a.id, c.id, 'n' FROM crm_accounts a JOIN crm_contacts c ON c.account_id = a.id WHERE a.code = 200;
SELECT (SELECT count(*) FROM crm_contacts) AS contactos_antes, (SELECT count(*) FROM crm_notes) AS notas_antes;
DELETE FROM crm_accounts WHERE code = 200;
SELECT (SELECT count(*) FROM crm_contacts) AS contactos_despues, (SELECT count(*) FROM crm_notes) AS notas_despues;
\echo === 9. borrar el tenant deja la cuenta sin vinculo (SET NULL), no la borra
INSERT INTO crm_accounts (code, tenant_id, name, name_norm) VALUES (300, 't105', 'f', 'f');
DELETE FROM events WHERE tenant_id = 't105'; DELETE FROM tenants WHERE id = 't105';
SELECT tenant_id IS NULL AS desvinculada FROM crm_accounts WHERE code = 300;
