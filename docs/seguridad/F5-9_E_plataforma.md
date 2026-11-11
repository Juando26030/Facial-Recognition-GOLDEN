# Revisión de seguridad F5-9 · E — plataforma, operaciones, despliegue y migraciones

Revisor E, 9-nov-2026. Alcance: `git diff 2c8c4d7..f5/integracion` (producción corre `2c8c4d7`, migración 0104) en alertas de borrado masivo (9-A), copia semanal a
OneDrive (9-B), gastos de infraestructura y de eventos (9C/9D), `deploy/gcp/config.sh`/`deploy.sh` y las migraciones 0105…0121. Entorno sin Postgres:
lo que depende de la base se escribió como prueba pytest y se verificó lo puro (cifrado, BigQuery simulado, cadena de migraciones, listas de secretos con bash).

## Hallazgos

| id | severidad | archivo:línea | escenario concreto | estado | prueba |
|----|-----------|---------------|--------------------|--------|--------|
| E-1 | Alta | `app/routers/system_alerts.py:64,104,120` | Un admin comprometido (o malintencionado) apaga la alerta (`enabled=false`), sube el umbral o pausa/quita a todos los destinatarios y después borra en masa: nadie se enteraba y no quedaba rastro (ni `audit_actions`). | Arreglado: todo cambio que debilite la alerta (umbral distinto, pausar o quitar destinatario) envía ANTES del cambio un aviso `alert_config` a los destinatarios activos (incluido el que se quita) y queda en `audit_actions`; el correo quitado va enmascarado. | `tests/test_alertas_borrado.py::test_disabling_alerts_or_removing_recipients_warns_current_recipients`, `test_saving_same_settings_does_not_warn` |
| E-2 | Media | `app/mass_delete.py:162` | Evasión de la regla «≥N en M minutos»: solo se registraban en `mass_delete_log` las acciones de ≥10 filas, así que borrar de a 9 personas por petición (o de a 1) nunca sumaba. | Arreglado: con una cuenta identificada se registra todo borrado (≥1 fila); sin cuenta (Jobs) sigue el mínimo de 10. Es un INSERT + una suma con índice en la misma transacción de un borrado: nada periódico. | `test_one_by_one_deletes_add_up_in_the_window` |
| E-3 | Baja | `app/mass_delete.py` (`_evaluate`) | `mass_delete_log` crecía sin límite (la docstring decía «se limpia sola» y no había purga). | Arreglado: al escribir se borran filas de más de 24 h (`LOG_KEEP_HOURS`). | `test_old_mass_delete_log_rows_are_pruned` |
| E-4 | Media | `app/offsite_copy.py:395` (`prune`) | Quien tenga escritura en la carpeta de SharePoint deja 8 archivos `golden_db_2099….gwbk`: como la retención ordenaba por nombre, cada copia real se borraba justo después de subirse y el estado decía «copia subida». | Arreglado: solo cuentan nombres `golden_db_AAAAmmdd_HHMM.gwbk` con fecha no futura; nunca se borra la recién subida; lo ajeno no se toca. | `tests/test_copia_semanal.py::test_planted_future_copies_cannot_make_the_real_copy_be_deleted` |
| E-5 | Baja | `app/offsite_copy.py:262` | `@odata.nextLink` se seguía con el token `Bearer` sin verificar el host. | Arreglado: solo enlaces de `https://graph.microsoft.com/v1.0/`. | `test_foreign_next_link_does_not_receive_the_token` |
| E-6 | Media (funcional) | `app/infra_costs.py:462` | `google.cloud.bigquery` no está en `requirements.txt`: la importación de costos de Google fallaba siempre en producción. | Arreglado (encargo del coordinador): API REST de BigQuery con `google.auth` + `AuthorizedSession` (scope `bigquery.readonly`), `jobs.query` (`useLegacySql: false`, `parameterMode: NAMED`, `@ym`), espera con `getQueryResults` si `jobComplete=false`, paginación `pageToken`, tope 50 s y 50 páginas; errores sin consulta, token ni cuenta. Sin dependencias nuevas. | `tests/test_gastos_infra.py::test_query_gcp_rest_*` |
| E-7 | Baja | `app/infra_costs.py:390` | La validación de `GCP_BILLING_EXPORT_TABLE` admitía `:`, `-` y puntos de más en el proyecto (`a.b.c.d`); el valor se interpola entre comillas invertidas. | Arreglado: expresión estricta `proyecto(6-30, minúsculas/dígitos/guion).conjunto.tabla`; el proyecto de la consulta sale de la primera parte. | `test_gcp_table_rejects_injection` (10 casos), `test_gcp_table_accepts_real_export_name` |
| E-8 | Media (funcional/despliegue) | `deploy/gcp/config.sh:126` | Con `SPLIT_SERVICE_ACCOUNTS=1`, `publico` (sirve `/f/` y `/webhooks/`) no recibía `PAYMENT_KEYS_ENCRYPTION_KEY`: los cobros con cuentas de terceros (0118) no podían firmarse ni verificarse los eventos de Wompi. | Arreglado: se agrega a `SECRETS_PUBLICO`. Ver decisión D-2. | `tests/test_secretos_por_servicio.py` |
| E-9 | Baja | `app/routers/gastos.py`, `app/routers/gastos_eventos.py` | Con `ENFORCE_STAFF_TENANT=1`, un admin con `tenant_id` (personal de otra empresa) veía los gastos de la plataforma y la satisfacción/comentarios de TODOS los clientes. | Arreglado: `require_platform_role("admin")` (`app/auth.py:130`) exige personal global cuando el aislamiento está encendido. | `test_tenant_scoped_admin_cannot_see_platform_panels` |
| E-10 | Info | `alembic/versions/0119_system_alerts.py:14` | La migración siembra un correo personal (Gmail) como destinatario en un repositorio público. | Sin cambio (decisión D-3). | — |

Revisado sin hallazgo: permisos de `/api/system-alerts/*` y `/api/gastos/*` (todo `require_role("admin")`, «admin» como rol extra solo lo da el Super Admin);
XSS en `system-alerts-admin.js`, `gastos-infra.js` y `gastos-eventos.js` (todo escapado o `textContent`; delegación de eventos; `showConfirm` con texto escapado);
exportaciones a Excel pasan por `xlsafe.safe_workbook`; adjuntos de gastos (tipo por lista + firma mágica, ≤5 MB, clave `infra-costs/<id>/<ts>.<ext>` generada, nombre
saneado, descarga como adjunto `no-store`); Neon (llave solo en encabezado, error sin detalle); formato `.gwbk` (truncado, reordenado, datos de más y llave errónea se
detectan; probado con `cryptography` 50); `open_backup_copy.py` (llave por entorno o `getpass`, nunca argumento; no deja archivo a medias); la URL de sesión de carga va
sin token y no se registra (solo la ruta final); nombres de carpeta/archivo en Graph se codifican con `quote` y la carpeta quita `.`/`..`; estado de la copia en el bucket
de respaldos (solo lo escribe la cuenta del Job); nada de lo nuevo consulta la base de seguido (`/sistema` lee el estado de la copia del bucket; la importación de Google es
mensual); staging excluye `onedrive-*`, `backup-copy-encryption-key`, Microsoft y Wompi de producción (además, sus secretos llevan sufijo `-staging`).

## Requiere decisión de Juan David

- **D-1 (permisos de nube, no los crea Claude):** la cuenta de servicio del Job de operaciones necesita `roles/bigquery.jobUser` en `goldenweb-prod` y
  `roles/bigquery.dataViewer` sobre el conjunto `billing_export`. Variable: `GCP_BILLING_EXPORT_TABLE=goldenweb-prod.billing_export.gcp_billing_export_v1_01D3FA_9264E8_E8058D`.
  Si Google respondiera «insufficient scope» con `bigquery.readonly`, cambiar `BQ_SCOPE` a `cloud-platform`.
- **D-2:** con E-8, `publico` puede descifrar también la llave PRIVADA de las cuentas de cobro de terceros (misma `PAYMENT_KEYS_ENCRYPTION_KEY`). Si se quiere
  mantener la regla «publico sin llave privada», hace falta una segunda llave solo para `private_enc` (cambio de datos: no se hizo).
- **D-3:** sacar el Gmail personal de `0119` (repo público) y sembrar solo `callcenter@…`, o dejarlo. Ya está en el historial de git; cambiarlo solo afecta instalaciones nuevas.
- Cualquier admin puede seguir cambiando la configuración de alertas (ahora con aviso y rastro). Si se prefiere, se restringe a `super_admin`.

## Cadena de migraciones

Verificado leyendo los archivos con `ast` (`tests/test_cadena_migraciones.py`, corre sin base):

```
0104_pledge_health_flags → 0105_event_billed → 0106_survey_delivery → 0107_inventory_catalog → 0108_event_change_log → 0109_inventory_unify
→ 0110_notifications → 0111_event_lease → 0112_local_nodes → 0113_public_slug → 0114_exhibitor_leads → 0115_kiosk_selfreg → 0116_queue_turns
→ 0118_payment_accounts → 0119_system_alerts → 0121_infra_costs   (única cabeza; no existen 0117 ni 0120: 0118 baja de 0116 y 0121 de 0119)
```

- Una sola raíz y una sola cabeza (`0121_infra_costs`); todo `down_revision` existe.
- Revision ids de 16 a 22 caracteres (≤ 32).
- Sin `SET` de sesión, advisory locks, `LISTEN/NOTIFY` ni tablas temporales en 0105…0121.
- Toda columna `NOT NULL` agregada a una tabla existente trae `server_default` (`web_forms.is_primary`, `events.selfreg_enabled`, `events.queue_enabled`); las demás
  columnas nuevas de tablas existentes son anulables. El resto son tablas nuevas.
- Todas tienen `downgrade`; la única nula es `0109_inventory_unify` (solo datos, idempotente, no borra nada; documentado).
- Permisos de `golden_app`: 0106 y 0108 hacen `GRANT`; el resto queda cubierto por `ALTER DEFAULT PRIVILEGES` de `scripts/neon_app_role.py` (en la VM `golden_app` es dueño).
- Modelo ↔ migración: comparé tipo, `nullable`, `unique` y `ondelete` de cada columna creada/agregada en 0105…0121 contra `app/models.py`: sin discrepancias
  (las únicas diferencias aparentes, `local_nodes.name`/`token_hash` únicos, están como `UniqueConstraint` en 0112).
