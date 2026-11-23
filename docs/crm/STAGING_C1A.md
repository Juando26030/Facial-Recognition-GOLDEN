# CRM C1a — primera ejecución real de la migración (staging) y criterios de éxito

La migración `0130_crm_cuentas_base` se ejecuta **por primera vez en el despliegue a staging**, con respaldo de Neon staging antes. No toca producción. Despliegue manual desde la Cloud Shell dueña (lo corre Juan David; GitHub Actions sigue bloqueado). Nada a `main`, ni despliegue, ni migración en producción sin su autorización explícita para esa acción y con respaldo.

## Antes
1. Respaldo de Neon staging (rama/instantánea) y anotar su identificador.
2. Anotar la huella de los códigos de cliente actuales: `SELECT count(*), md5(string_agg(client_code, ',' ORDER BY id)) FROM tenants;`
3. Pruebas: ver «Pruebas» abajo (todas pasando).

## Criterios de éxito (todos deben cumplirse)
1. El Job de migraciones termina sin error y `alembic_version` = `0130_crm_cuentas_base`.
2. Las 5 tablas `crm_*` existen y están vacías; `crm_counters` tiene 2 filas (`account`, `event`) con `ready = false`.
3. `tenants.legacy_client_code` existe y es NULL en todas las filas; la huella del paso 2 de «Antes» es **idéntica** (ningún `client_code` cambió).
4. `/health` y `/ready` responden bien; `/sistema` no muestra chequeos rojos nuevos y no aparece «CRM» (está apagado).
5. Lo existente sigue igual: lista de Clientes, selector de cliente en Nuevo evento, crear un cliente (código hexadecimal de 8 caracteres), exportar un evento y volver a importarlo en staging.
6. No existen rutas `/crm` (404): C1a no las tiene.
7. Los logs del Job y de la app no contienen nombres, correos ni teléfonos.
8. Reversa probada en una **copia** (rama de Neon creada desde el respaldo, nunca en el staging en uso): `alembic downgrade 0129_staff_client_temp` deja `client_code` con su valor anterior y sin tablas `crm_*`; `alembic upgrade head` vuelve a subir.
9. Prueba del interruptor con datos ficticios en staging: con `CRM_ENABLED=1` y contador sin fijar, `/sistema` muestra «CRM encendido sin contador» (rojo) y crear cliente responde 409; tras `crm_set_counter.py --name account --floor 900000 --apply`, `/sistema` pasa a verde y el siguiente cliente recibe `900001`. Luego `CRM_ENABLED=0`.

## Pruebas (sin ejecutar al entregar C1a)
`pytest` necesita PostgreSQL y las librerías de Python; el entorno de la sesión que programó C1a no podía instalarlas. Se corren con el procedimiento del documento 43 del proyecto (sesión con instalación de paquetes encendida: Postgres 16 local, `pip install -r requirements.txt`, `alembic upgrade head`, suite completa): `python -m pytest -q` y, en particular, `tests/test_crm_*.py tests/test_account_sync.py tests/test_event_transfer.py`. Sin pruebas pasando no se despliega.
Verificado en la sesión de C1a: `ruff check` y las pruebas «de texto» (`--noconftest tests/test_crm_texto.py`), y el SQL de la migración, el contador y la concurrencia con `docs/crm/verificacion_sql/correr.sh`.
