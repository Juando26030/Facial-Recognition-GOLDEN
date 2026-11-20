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
