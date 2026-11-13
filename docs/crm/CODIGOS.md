# CRM — códigos consecutivos

## Regla
- El código de una cuenta es un **número consecutivo** que el sistema asigna solo al crear (no hay botón «generar código»). Continúa el consecutivo de SuiteCRM: parte del código más alto que ya exista.
- La plataforma adopta ese mismo número como código de cliente (`tenants.client_code`, texto). El hexadecimal anterior se guarda en `tenants.legacy_client_code` (alias; sirve para leer paquetes de eventos exportados antes del cambio).
- La migración `0130` NO cambia ningún `client_code` existente. Los clientes viejos pasan al número nuevo en C1c, después de un informe de emparejamiento (seguros / dudosos / sin pareja) que Juan David revisa.
- Código de evento: sigue pidiéndose a mano en `create_event`. Pasará a automático en C4, cuando se vea el formato real de «Código Proyecto» y se asegure que el contador `event` quede por encima de todo código importado. El contador `event` ya existe (no listo).
- Una sola función (`app/crm/codes.py::next_code`) entrega los números: un `UPDATE … RETURNING` con bloqueo de fila, sin huecos (un rollback no consume número) y saltando los ocupados (clientes, alias, cuentas del CRM y eventos con código numérico).

## Orden para encender el CRM (importante)
1. Respaldo de Neon del entorno (en producción, con autorización explícita de Juan David para esa acción).
2. Migración `0130_crm_cuentas_base` aplicada (el contador nace **no listo**).
3. **Primero el contador:** `python scripts/crm_set_counter.py --name account --floor N` (simulacro por defecto) y luego con `--apply`. `N` = el ÚLTIMO número ya usado.
   - **En producción, `N` es el mayor entre (a) el código de cuenta más alto de SuiteCRM (de la exportación) y (b) el mayor número ya presente en `tenants`.** El siguiente entregado será `N + 1`.
   - Para (b), contar solo códigos numéricos reales, no los hexadecimales que por azar son solo dígitos (esos tienen siempre 8 caracteres y los consecutivos son menores de 10.000.000): `SELECT max(client_code::bigint) FROM tenants WHERE client_code ~ '^[0-9]{1,7}$';` (y lo mismo con `legacy_client_code`, por prudencia).
   - **`900000` es SOLO de staging** (datos ficticios, criterio 9 de `docs/crm/STAGING_C1A.md`). Nunca se usa en producción: dejaría un hueco enorme y chocaría con el orden real de SuiteCRM.
4. **Después el interruptor:** `CRM_ENABLED=1` en el servicio `web` de la nube (nunca en el servidor local).
5. Comprobar en `/sistema`: aparece el chequeo «CRM» en verde («encendido»). Crear un cliente de prueba (en staging) y ver que recibe `N + 1`.

Si se enciende en el orden contrario: `/sistema` muestra «CRM encendido sin contador» en rojo y crear un cliente responde 409 con un mensaje claro (no entrega números bajos). Para volver atrás basta `CRM_ENABLED=0`: se vuelve al hexadecimal y los clientes ya creados con número siguen siendo válidos.

## Notas
- Un hexadecimal de 8 caracteres puede ser solo dígitos (por azar); `next_code` lo trata como ocupado si coincide.
- `scripts/wipe_all_data.py` (vacía TODAS las tablas del modelo, incluidas las `crm_*`, y no tiene bloqueo por entorno: solo pide escribir el nombre de la base) y las pruebas vacían `crm_counters`; sin fila, `next_code` se niega (no listo) y `crm_set_counter.py` la vuelve a crear.
- Reversa de la migración: restaura `client_code` desde `legacy_client_code` antes de quitar la columna. Caso límite: falla si un número actual coincide con el hexadecimal de otro cliente (solo con contador sobre 10.000.000; `next_code` evita entregarlos).
