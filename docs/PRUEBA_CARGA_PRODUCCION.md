# Prueba de carga «rush» en PRODUCCIÓN (autorizada el 19-nov-2026)

Orden expresa de Juan David (19-nov-2026): repetir en producción la prueba de 40.000 escaneos de cédula que se hizo en staging, **en un evento sintético que se borra al terminar**.
Es una EXCEPCIÓN a «pruebas de carga nunca contra producción» (CLAUDE.md) y solo vale por este procedimiento; cualquier otra prueba contra producción sigue prohibida.

## Qué se toca y qué no
- **Se crea:** el cliente `carga-staging`, el evento `LOAD-STG` (id nuevo), 40.000 personas sintéticas, 40.000 ingresos de la prueba, la cuenta `carga_dig`. Todo se borra con `purge-data`.
- **Se cambia temporalmente en el servicio `golden-web`:** `DIGITADOR_LOGIN_CONTROL=0` y `SINGLE_SESSION=0` (limits-up) y, si se pide, mínimo/máximo de instancias (scale-up). Se devuelven con limits-down y scale-down.
- **No se toca:** `golden-publico`, `golden-biometria`, formularios públicos, el dominio `app.golden-eventos.com`, Cloudflare ni Firebase. La carga entra por la URL de Cloud Run de `golden-web`.

## Candados (todos en `deploy/loadtest/run_phase4.sh`, `scripts/seed_load_staging.py`, `scripts/load_cfg.py`)
1. `LOAD_TARGET=production` **y** `LOAD_PROD_CONFIRM=<ID exacto del proyecto>`; se niega con un proyecto de staging.
2. Solo estos pasos: build, seed, run **rush**, report-rush, verify, reset-data, purge-data, limits-up/down, scale-up/down, cleanup.
3. El generador solo acepta como destino la URL `*.run.app` del servicio web (lista exacta); nunca `golden-eventos`, HTTP, otro servicio ni otro sitio.
4. La siembra se niega si hay **un evento real en proceso** (`LOAD_ALLOW_LIVE=1` lo salta, a propósito).
5. `scale-up` exige `SCALE_WEB='<mín> <máx>'` explícito; `limits-up` se niega si las dos variables ya existen en el servicio (limits-down las borraría).

## Orden (desde `~/gw-hosting`, con `CLOUDSDK_CORE_PROJECT=<proyecto de producción>`, `REGION=us-east4`)
Prefijo de cada comando: `LOAD_TARGET=production LOAD_PROD_CONFIRM=<proyecto>`.
`build` → `SCALE_WEB='<mín> <máx>' scale-up` → `limits-up` → `LOAD_PEOPLE=40000 seed` → `LOAD_PEOPLE=40000 run rush` → `report-rush <ejecución completa>`.
Al terminar, SIEMPRE: `limits-down` → `scale-down` → `purge-data` (escribir `LOAD-STG`) → `cleanup`.
Si algo sale mal a medias: `limits-down` y `scale-down` primero (devuelven producción), después `purge-data`.

## Evento de prueba en un cliente existente (19-nov-2026)
- `... run_phase4.sh info` (solo lectura): lista los clientes cuyo nombre contiene «prueba» y los eventos reales en proceso (id, cliente, fechas, ingresos de la última hora; sin datos de personas).
- `LOAD_TENANT=<id del cliente> ... run_phase4.sh seed|verify|reset-data|purge-data`: la prueba vive en ese cliente. El cliente NUNCA se crea ni se borra; el borrado solo quita el evento `LOAD-STG`, las personas sintéticas (nombre «Persona», entidad «Sintética», cédula 9xxxxxxxxx) y la cuenta `carga_dig`.
- Con eventos reales en proceso la siembra se niega; `LOAD_ALLOW_LIVE=1` solo con OK explícito de Juan David.

## Resultado y lecciones de la prueba del 19-nov-2026 (producción, cliente `prueba`, evento 20)
- 40.000 escaneos en ~100 s (~400/s), 0 fallos, 0 5xx, 99,9 % ok a la primera; web 12–30 instancias. p95 búsqueda por nombre 2,4 s (meta 1,5 s) → NO CUMPLE por poco; p95 de cédula conocida 2,2 s (casi igual: apunta a la ráfaga de arranque, no a la búsqueda; hipótesis sin medir). Staging (1 vCPU, máx 10): 127/s, p95 4,5 s.
- `verify`: 0 duplicados, 0 sobrecupo, 31.912 ingresos = respuestas 200 de cédula conocida.
- Todo restaurado: `limits-down`, `scale-down` (min 2 / máx 10), `purge-data`, `cleanup`; sin `DIGITADOR_LOGIN_CONTROL`/`SINGLE_SESSION` en el web; staging apagado (`staging_power.sh off`).
- El Job generador en producción corre con la cuenta de la app (la de Compute no lee `golden-ops-token`).
- `audit_*` (consentimientos) es inmutable y sin llaves foráneas: la limpieza NO las borra (el rol no puede) y las informa como `<tabla>_kept`.
