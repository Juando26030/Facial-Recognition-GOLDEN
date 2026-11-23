#!/usr/bin/env bash
# Concurrencia del contador: N sesiones psql simultáneas piden número, insertan su cuenta y confirman. Esperado: N códigos distintos y consecutivos, sin huecos ni errores.
# Uso: PSQL="psql -h /tmp/pgc -p 55432 -U pgtest -d crmtest -q -tA" ./05_concurrencia.sh [N]
N="${1:-40}"
PSQL="${PSQL:?define PSQL con la conexión a la base de verificación}"
$PSQL -c "SELECT crm_bump_floor('account', 1000);" >/dev/null
START=$($PSQL -c "SELECT value FROM crm_counters WHERE name='account'")
for i in $(seq 1 "$N"); do
  ( $PSQL -c "BEGIN; INSERT INTO crm_accounts (code, name, name_norm) VALUES (crm_next_code('account'), 'c$i', 'c$i'); SELECT pg_sleep(0.05); COMMIT;" >/dev/null 2>"/tmp/crm_conc_err_$i" ) &
done
wait
ERRS=$(cat /tmp/crm_conc_err_* 2>/dev/null | grep -c .)
$PSQL -c "SELECT 'inicio=$START', 'insertadas=' || count(*), 'distintos=' || count(DISTINCT code), 'min=' || min(code), 'max=' || max(code), 'consecutivos=' || (max(code)-min(code)+1 = count(*)), 'errores=$ERRS' FROM crm_accounts WHERE code > $START;"
rm -f /tmp/crm_conc_err_*
