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

## Solicitudes de supresión de un contacto del CRM (para C1b)
El flujo de la plataforma por cédula (`privacy.erase_person`, `DELETE /api/attendees/{id}/purge-data`) **no cubre** estos datos: los contactos del CRM no tienen cédula. Cómo se atiende:
1. **Quién:** solo admin o super_admin. Pantalla «Eliminar contacto (supresión)» dentro de la cuenta, con `showConfirm` que muestra qué se borra y pide el motivo.
2. **Qué hace:** llama `app/crm/erase.py::erase_contact`, que borra en una transacción el contacto, las notas que lo señalan (`crm_notes.contact_id`) y su historial (`crm_change_log`, entity `contact`). Para una cuenta completa, `erase_account`.
3. **Qué NO alcanza solo:** (a) el nombre o correo escrito a mano dentro del texto de notas de la cuenta, llamadas, tareas y cotizaciones (C2/C3): la pantalla debe ofrecer una búsqueda por texto del correo/nombre para revisarlo y editarlo; (b) el contacto único del cliente en `tenants.contact_*` si es la misma persona (ver pregunta abierta de abajo); (c) las copias de respaldo de Neon y de Cloud Storage, que se vencen por su política de retención.
4. **Constancia:** `audit_actions.record(..., "erase", "crm_contact", <id>, ...)` con SOLO conteos y el id, nunca nombres ni correos.
5. **Respuesta al titular:** dentro de los plazos de la Ley 1581 (10 días hábiles para consultas, 15 para reclamos).
6. **Prueba:** `tests/test_crm_modelos.py` comprueba que borrar un contacto borra sus notas y su historial.

## Preguntas abiertas de C1b
1. **Contacto único del cliente (`tenants.contact_name/phone/email`) frente a los contactos del CRM — DECIDIDO (Juan David, 11-nov-2026): manda el CRM.** Los `tenants.contact_*` se rellenan desde el **contacto principal** de la cuenta vinculada, **en un solo sentido** (CRM → cliente), sin cambiar nada de lo que sincroniza `account_sync` (sigue enviando `tenants.contact_*` tal cual). Detalles que el plan de C1b debe resolver (no están programados): con cuenta vinculada, Clientes muestra esos campos de solo lectura; sin cuenta vinculada se editan como hoy; qué pasa si la cuenta queda sin contacto principal (propuesta: se conservan los valores, no se borran); al suprimir al contacto principal, también se limpian los `tenants.contact_*` que se copiaron de él. **C1b no se programa hasta que Juan David apruebe su plan.**
2. Listas de valores (etapas, formas de pago, plazos) y valores reales de «cierre de facturación» (campos hoy en texto).
3. Dónde se enciende `CRM_ENABLED=1` en la configuración de la nube (`deploy/gcp/env/`) y cómo se enlazan las rutas `/crm` al modo `web` (`app/appmode.py`).
