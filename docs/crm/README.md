# CRM de GoldenWeb — reglas del módulo

El CRM es un **módulo de `golden-web`** (mismo repositorio, misma imagen, mismas migraciones de Alembic, mismo diseño). Decisiones: `docs/crm/` (este directorio) y, en el proyecto de Claude, los documentos 48 al 53.
Estado: **C1a** (tablas, códigos consecutivos, registro de cambios). Sin pantallas ni rutas: eso es C1b. Importador de SuiteCRM: C1c.

## Dónde vive cada cosa
- Código: `app/crm/` (`__init__.py` interruptor y estados, `codes.py` contador, `history.py` registro de cambios, `erase.py` supresión); rutas futuras `app/routers/crm_*.py`; plantillas `templates/crm_*.html`; scripts `static/js/crm_*.js`, `static/css/p-crm.css`.
- Tablas `crm_*` en el esquema `public` (`crm_counters`, `crm_accounts`, `crm_contacts`, `crm_notes`, `crm_change_log`) y `tenants.legacy_client_code`. Migración `0130_crm_cuentas_base`.
- Pruebas: `tests/test_crm_*.py` (+ ampliaciones en `test_account_sync.py` y `test_event_transfer.py`). Verificación del SQL con psql: `docs/crm/verificacion_sql/`.

## El CRM solo corre en internet
`CRM_ENABLED` (por defecto 0): con 0 no hay rutas `/crm` y `create_tenant` entrega el código hexadecimal de siempre. El servidor local **nunca** lo enciende. Las tablas `crm_*` llegan vacías a cualquier entorno que corra las migraciones (no estorban). Lo que se crea en el CRM llega al local solo como cliente y evento, por la sincronización que ya existe. Orden para encenderlo: `docs/crm/CODIGOS.md`.

## Registro de cambios
`crm_change_log` tiene la misma forma que `person_change_log` (campo, valor anterior, valor nuevo, quién, cuándo, origen) y se usa con el mismo patrón (`app/crm/history.py`: `snapshot` antes, `record` después, sin commit propio). No es la misma tabla porque `person_change_log` se borra y se exporta por persona y por evento.

## Estados de cuenta
La lista (`ACCOUNT_STATUSES` en `app/crm/__init__.py`) se valida en el código, no con CHECK en la base, hasta ver la exportación de SuiteCRM. Cambiarla no necesita migración.

## Datos personales (Ley 1581 de 2012)
- `crm_contacts` (nombre, cargo, correo, teléfonos), `crm_notes` y `crm_change_log` guardan datos personales. Nunca van a logs (`app/obs.py` no los recibe), a repositorio, a documentos ni al chat.
- Staging solo con datos ficticios. Datos reales únicamente a producción, con respaldo previo en Neon y autorización explícita de Juan David para esa acción. Antes de cargar contactos reales: aviso a la auditora (borrador en el documento 53 del proyecto).
- Las exportaciones de SuiteCRM se guardan solo en carpeta temporal y se borran al terminar.

## Solicitudes de supresión de un contacto del CRM (C1b-1: API hecha; pantalla en C1b-3)
El flujo de la plataforma por cédula (`privacy.erase_person`, `DELETE /api/attendees/{id}/purge-data`) **no cubre** estos datos: los contactos del CRM no tienen cédula. Cómo se atiende:
1. **Quién:** solo admin o super_admin (`POST /api/crm/contacts/{id}/erase`, `POST /api/crm/accounts/{id}/erase`). Pide el **motivo** y que se escriba el nombre del contacto (o de la cuenta).
2. **Qué hace (`app/crm/erase.py`, una transacción).** Un contacto deja rastro en cinco sitios y los cinco se limpian:
   1. su fila y sus notas (`crm_contacts`, `crm_notes.contact_id`);
   2. su propio historial (`crm_change_log`, entidad `contact`);
   3. **el historial de la CUENTA** que traiga sus valores: se borran las filas de `crm_change_log` (entidad `account`) de los campos `email`, `phone`, `billing_contact_name` y `billing_contact_phone` cuyo valor anterior o nuevo coincida con su nombre, correo o teléfono (comparación sin tildes ni mayúsculas; teléfonos por dígitos, mínimo 7);
   4. **los campos actuales de la cuenta** con esos mismos valores: se dejan vacíos, **sin escribir historial** (el valor anterior es justo el dato a suprimir);
   5. **la copia en `tenants.contact_name/phone/email`** (regla del contacto principal): se vacía cada campo que coincida. `account_sync` entrega el vacío al servidor local y `apply` lo sobrescribe (prueba en `tests/test_crm_supresion.py`).
3. **Limitación conocida (servidor local):** `account_sync` solo entrega a un servidor local las empresas que usa alguna cuenta del personal. Si una empresa dejó de usarse allí, su fila local conserva los datos de contacto que tenía y la supresión de la nube ya no le llega. Hay que vaciarla a mano en el local o reasignar la cuenta; queda como pendiente de decisión.
4. **Qué NO se puede decidir solo:** el texto libre (descripción de la cuenta, notas generales, y más adelante llamadas, tareas y cotizaciones). Se cuenta si parece nombrarse a la persona (`review`: descripción sí/no, número de notas generales) y la pantalla (C1b-3) lo muestra en un aviso destacado y persistente, ver «Aviso de revisión» más abajo. Tampoco alcanza las copias de respaldo de Neon y de Cloud Storage, que se vencen por su política de retención.
5. **Constancia:** `audit_actions.record(..., "erase", "crm_contact", <id>, <nombre de la CUENTA>, "motivo; conteos")`. Nunca el nombre, correo ni teléfono de la persona. El motivo es texto libre del administrador: que no lleve datos personales.
6. **Respuesta al titular:** dentro de los plazos de la Ley 1581 (10 días hábiles para consultas, 15 para reclamos).
7. **Pruebas:** `tests/test_crm_supresion.py` (extremo a extremo, con base de datos), `tests/test_crm_c1b_texto.py` (reconocer a la persona, sin base de datos).

## Aviso de revisión tras suprimir (diseño para C1b-3)
Al terminar la supresión la pantalla NO cierra con un aviso pasajero (`showToast`): abre un panel de resultado que se queda hasta que la persona lo cierre, con estilo de advertencia (`.gw-*` de alerta del sistema visual) y con los conteos de `counts.review`: «La descripción de la cuenta parece mencionar a esta persona» (con botón «Abrir la descripción») y «N notas generales parecen mencionarla» (con botón «Ver las notas»). Si ambos son cero muestra la confirmación normal en verde. Primero el aviso, después el botón «Entendido». Lo ideal, y lo propongo para C1b-3, es mostrar un adelanto de esos mismos conteos en la ventana de confirmación ANTES de borrar.

## Búsqueda sin tildes (C1b-1)
Sin `unaccent` ni migración: la búsqueda normaliza el texto buscado en Python (`app.crm.normalize`: minúsculas, sin tildes, espacios colapsados) y lo compara con `crm_accounts.name_norm`, `crm_contacts.full_name_norm` y `crm_contacts.email_norm`, columnas que **ya existen desde C1a** y se guardan normalizadas al escribir. Por eso esas columnas **solo se escriben desde `app/crm/accounts.py`** (y desde `tenants._create_crm_account`); una prueba de texto lo vigila. Además: código exacto y NIT sin puntos ni guiones. Es un barrido sin índice trigrama (los comodines de LIKE se escapan); alcanza hasta unos 20.000 registros (decisión D5). El importador de C1c debe llenar estas columnas con la misma función.

## Encendido por entorno (C1b-1)
`CRM_ENABLED` se fija en `deploy/gcp/config.sh`: **staging 1, producción 0** (producción solo con `CRM_ENABLED=1` en el comando y con autorización de Juan David). `deploy.sh` lo escribe en el servicio `web` en cada despliegue, porque `gcloud run deploy --env-vars-file` **reemplaza todas las variables**: un valor puesto a mano se pierde. Lo usan igual `deploy/gcp/manual_deploy.sh` (que muestra el valor antes de desplegar) y GitHub Actions, porque ambos pasan por `deploy.sh`. Las rutas `/api/crm/*` siempre están montadas, pero cada una responde 404 mientras el interruptor esté apagado.

## Preguntas abiertas de C1b
1. **Contacto único del cliente (`tenants.contact_name/phone/email`) frente a los contactos del CRM — DECIDIDO (Juan David, 11-nov-2026): manda el CRM.** Los `tenants.contact_*` se rellenan desde el **contacto principal** de la cuenta vinculada, **en un solo sentido** (CRM → cliente), sin cambiar nada de lo que sincroniza `account_sync` (sigue enviando `tenants.contact_*` tal cual). Detalles que el plan de C1b debe resolver (no están programados): con cuenta vinculada, Clientes muestra esos campos de solo lectura; sin cuenta vinculada se editan como hoy; qué pasa si la cuenta queda sin contacto principal (propuesta: se conservan los valores, no se borran); al suprimir al contacto principal, también se limpian los `tenants.contact_*` que se copiaron de él. **C1b no se programa hasta que Juan David apruebe su plan.**
2. Listas de valores (etapas, formas de pago, plazos) y valores reales de «cierre de facturación» (campos hoy en texto).
3. ~~Dónde se enciende `CRM_ENABLED=1`~~ — RESUELTO en C1b-1 (ver «Encendido por entorno»). Las rutas `/crm` y `/api/crm` ya caen en el servicio `web` sin tocar `app/appmode.py` (prueba en `tests/test_crm_c1b_texto.py`).
