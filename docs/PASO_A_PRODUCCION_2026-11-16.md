# Paso a producción — CRM + novedades del 16-nov-2026 (PREPARADO; NO ejecutado)

Autorización de Juan David (16-nov-2026, 12:39): **«sí» para PREPARAR** el paso. Ejecutarlo requiere otro «sí» para ESA acción, con el commit exacto. Claude no corre nada en la nube: lo ejecuta Juan David en Cloud Shell.

## Commit a desplegar
`e9e3ce85a8ccdf97dd7205a2b5956167a9e36a36` (el mismo que corre y se probó en staging; los commits posteriores son solo de documentación).

## Qué llega (rama `crm/importar-aplicar`, ~99 commits sobre `f5/integracion`, que es lo que corre hoy)
- **CRM completo** (cuentas, contactos, oportunidades, cotizaciones con diseñador de PDF, plantillas, productos, importación de SuiteCRM). **Apagado en producción** (`CRM_ENABLED=0` por defecto; no se enciende sin autorización aparte y sin fijar el contador con `scripts/crm_set_counter.py`).
- **Eventos:** duplicar evento; borrar la base cargada (Adjuntar BD); código sugerido (siguiente al más alto numérico; se puede escribir a mano); **contactos del cliente por evento** (varios, uno principal, por defecto el principal del CRM; a mano exigen teléfono y correo; los «INACTIVO» no se ofrecen).
- **Correos:** el informe final también va al contacto principal; la encuesta/entrega se **envía sola al contacto principal al pasar a «Facturado»** (un correo por enlace y hora).
- **Migraciones nuevas: 0130 → 0145** (una sola cabeza `0145_event_contacts`, ids ≤ 32 caracteres). Todas **solo agregan** (tablas, columnas con valor por defecto, índices); las bajadas existen pero **no se usan**: el código anterior ignora lo nuevo, así que volver atrás de código NO exige tocar la base.

## Verificado antes de preparar
- Staging corre exactamente el commit candidato (ver «Commit a desplegar») y se probó: contactos (crear/editar/duplicar/borrar por Ley 1581), código sugerido, informe y encuesta automática (sin correo real: staging no tiene correo configurado), inactivos fuera, a mano con teléfono y correo.
- `ruff check .` limpio; pruebas de JS puras en verde; una sola cabeza de Alembic.
- **No verificado:** las pruebas con base de datos (no hay Postgres en el entorno de Claude) y el CI de GitHub (Actions está bloqueado por facturación). Ese riesgo lo cubre el ensayo en staging.

## Antes de ejecutar (checklist de Juan David)
1. **Sin evento en curso** (el despliegue respeta el congelamiento; no uses `FORCE=1`).
2. **Respaldo:** Neon → proyecto de producción → Branches → Create branch → «Current point in time» → `antes-produccion-16nov`. No la borres hasta pasada una semana.
3. Decidir el commit exacto (el último de `crm/importar-aplicar` que se probó en staging: el que diga el mensaje de Claude).
4. Confirmar que **no** se pasa `CRM_ENABLED=1`.

## Ejecución (un solo comando, en Cloud Shell, proyecto de producción)
```
cd ~/gw-hosting && git stash push -u -q -m "antes-de-desplegar" ; git fetch -q && git checkout -q --detach e9e3ce85a8ccdf97dd7205a2b5956167a9e36a36 && nohup bash deploy/gcp/manual_deploy.sh production goldenweb-prod > ~/deploy.log 2>&1 &
```
(el script corre el Job de migraciones 0130→0145, despliega los 3 servicios y los Jobs, y publica Firebase; tarda ~15 min. Ver avance: `tail -f ~/deploy.log`.)

## Después (Claude lo verifica con Juan David iniciando sesión; yo no escribo contraseñas)
- `/sistema`: «Versión desplegada» = el commit; en verde.
- Crear un evento de prueba y borrarlo: código gris con el siguiente número; contactos del cliente aparecen (sin CRM: «agrega uno a mano»).
- Confirmar que el menú CRM **no** aparece (apagado).
- Correo: en producción sí hay Graph/SMTP → la primera encuesta/informe sí saldrá. Probar solo con un evento y un contacto propios de Juan David.

## Antes de mirar el código sugerido
En producción el código sugerido sale del número más alto SOLO NUMÉRICO que exista. Si hay un código con muchos dígitos (p. ej. 23060004), la serie empieza ahí. Revisar en producción: `SELECT max(event_code::int) FROM events WHERE event_code ~ '^[0-9]{1,9}$';` (lo corre Juan David en Neon → SQL Editor, rama `production`) y, si no es el esperado, corregir el código raro antes de crear eventos nuevos.

## Vuelta atrás
1. `gcloud run services update-traffic golden-web golden-publico golden-biometria --to-revisions <revisión anterior>=100 --region us-east4` (las revisiones anteriores salen en el encabezado del despliegue, «REVISIONES ACTUALES»).
2. La base se queda en 0145 (compatible). Solo si hubiera datos dañados: restaurar desde la rama `antes-produccion-16nov` (decisión aparte, con Claude).

## Pendientes que NO bloquean este paso
- Encender el CRM en producción y la importación definitiva de SuiteCRM con dueña `lyz.velandia` (`CRM_IMPORT_APPLY` queda en 0): otra autorización.
- Aviso a la auditora / Ley 1581 por los contactos nuevos del evento (nombre, teléfono, correo del cliente).
- Los contactos del evento no viajan en el paquete de exportar/importar evento.
- Datos de prueba que quedan en staging (eventos «borrar…», copias). Apagar staging: `REGION=us-east4 CLOUDSDK_CORE_PROJECT=goldenweb-staging bash deploy/gcp/staging_power.sh off`.
