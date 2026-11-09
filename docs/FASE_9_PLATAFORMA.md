# Fase 9 — Plataforma (alertas, copias, panel de gastos)

Estado: en construcción (nada desplegado). Se programa todo; un solo despliegue a staging y una sola corrida completa de pruebas al final.

## A. Alerta de borrado masivo (hecha, sin probar en la nube)

**Qué hace.** Si una acción borra muchos registros importantes de golpe, sale un correo al instante a los destinatarios configurados.
Cuenta: eventos, formularios, inscripciones, registros de asistentes, personas, registros de acceso, archivos de evento y cuentas del personal.

**Cuándo avisa** (configurable en Configuración → «Alertas del sistema», solo admin y super admin):
- una sola acción borra **≥ 50** registros, o
- la misma cuenta acumula **≥ 200** en **10 minutos**.
Los tres números se cambian ahí mismo (con límites para no dejar la alerta inútil) y la alerta se puede apagar.

**Qué dice el correo.** Quién (usuario y rol), qué se borró y cuántos, evento (nombre y número), fecha y hora de Bogotá y qué hacer. **Nunca** lleva datos de asistentes (ni cédulas, ni nombres, ni correos).
Además llega a la campana de las cuentas de la plataforma que estén en la lista.

**Quién recibe.** Se siembra con `juando02603@gmail.com` y `callcenter@goldenlogisticas.com` (migración `0119_system_alerts`). En la pestaña se agregan o quitan correos externos y cuentas de la plataforma (con correo registrado), se pausan sin borrarlos y hay botón «Enviar alerta de prueba».

**No es una alerta** (se marca como esperada): la purga programada de retención de biometría (`privacy.purge_expired`) y la de un evento finalizado (`privacy.purge_event`).

**Cómo funciona por dentro** (`app/mass_delete.py`).
- Se engancha a la sesión de SQLAlchemy: cuenta los `db.delete(...)` (después del flush) y los `query.delete()` (después del borrado masivo). No hay consultas periódicas: Neon puede apagarse.
- Antes de confirmar la transacción evalúa. Solo consulta la base si la acción borró **10 o más** filas (guarda esas acciones en `mass_delete_log` para sumar la ventana de la cuenta).
- La alerta (historial `system_alerts`, correos por la cola `system_alert_mail`, campana) entra en la MISMA transacción: si el borrado se revierte, no hay alerta. Al confirmar se despierta la cola.
- Si algo falla al evaluar, se registra en el log y el borrado de la persona sigue intacto (la alerta nunca bloquea).
- Una misma situación no repite correo: clave por cuenta + evento + tipo + tramo de la ventana.
- La cuenta que borra se toma de la sesión de la petición (`auth.get_current_staff`); sin cuenta (tareas del sistema) el correo dice «el sistema».

**Límites honestos.**
- Los `DELETE` escritos a mano con `text()` no se cuentan; en el código solo los usa la supresión de UNA persona y la purga esperada.
- Un borrado directo en la base de datos (fuera de la aplicación) no se detecta aquí; eso lo cubre el respaldo de Neon.
- El correo sale por el mismo servicio de correo de la plataforma: si no está configurado, queda guardado y se ve en el log.

**Archivos.** `app/mass_delete.py`, `app/routers/system_alerts.py`, `alembic/versions/0119_system_alerts.py`, `templates/configuracion.html` (pestaña), `static/js/system-alerts-admin.js`, `tests/test_alertas_borrado.py`.


## B. Copia semanal cifrada a OneDrive (hecha, sin probar contra Microsoft real)

**Qué hace.** Una vez por semana el Job de operaciones toma el respaldo más reciente del bucket, lo **cifra** (Fernet por trozos, llave nueva `BACKUP_COPY_ENCRYPTION_KEY`) y lo sube a una carpeta de OneDrive de la empresa por Microsoft Graph (autenticación de aplicación, sin usuario). Así hay una copia **fuera del proyecto de Google**, y aunque alguien viera el OneDrive, el archivo no se puede leer sin la llave.

- Código: `app/offsite_copy.py`; paso `offsite-copy` en `app/ops_runner.py` (corre cada hora pero solo copia cuando toca); tarea suelta: `python -m app.ops_runner offsite-copy`.
- Cuándo toca: no hay copia buena o la última tiene ≥ 6 días, ya pasadas las 6 a. m. (hora Bogotá) y sin intento en las últimas 6 h (`OFFSITE_EVERY_DAYS`, `OFFSITE_HOUR`, `OFFSITE_RETRY_HOURS`).
- Retención: últimas 8 copias (`OFFSITE_KEEP_WEEKS`, mínimo 2). Solo borra archivos `golden_db_*.gwbk` **dentro de la carpeta configurada**; nunca otras carpetas ni otros nombres.
- Resultado: `offsite/state.json` en el bucket de respaldos (fecha, tamaño, ok/fallo, motivo corto, últimas 20 corridas; sin datos personales ni secretos). Se muestra en `/sistema` como «Copia semanal fuera de Google» (verde ≤ 8 días, amarillo hasta 10, rojo después).
- Alertas: si una corrida falla, o pasan más de 10 días sin copia buena, el paso falla y el Job manda el correo de alerta de siempre (`ALERT_EMAIL`, máximo uno cada 6 h por causa).
- Sin variables de OneDrive: el paso responde «copia semanal no configurada» y no toca nada; `/sistema` lo muestra en amarillo con el enlace a la guía.
- Staging nunca recibe estos secretos (`deploy/gcp/deploy.sh` los salta) para que pruebas no suban copias a la carpeta real.
- Formato `.gwbk`: cabecera `GWBK1`, trozos de 8 MB cifrados cada uno con índice y marca de «último» (detecta truncado, trozos repetidos o desordenados). Abrir: `scripts/open_backup_copy.py` (en cualquier computador, sin la nube).
- Sin migración: el estado vive en el bucket (no consume la base de Neon).
- Memoria: el archivo se cifra y se sube por pedazos de 10 MiB; el tamaño cifrado se calcula antes y se comprueba al final.

**Pruebas:** `tests/test_copia_semanal.py` (21 casos con Graph simulado: cifrado, tamaño exacto, PUT simple y sesión por trozos con `Content-Range`, reintentos 503, retención, estado, alertas, `/sistema`, script de apertura). Los de cifrado, ejecución y script se corrieron localmente (sin Postgres) y pasaron; falta correr la suite completa y probar contra el Microsoft real.

**Lo que NO se pudo verificar** (Microsoft Learn bloqueó la lectura desde el entorno): forma exacta del endpoint de token v2, `PUT …/root:/ruta:/content`, `createUploadSession` con `Content-Range`, listado `children` y `DELETE`. Están escritos de memoria y documentados en `docs/24_COPIA_SEMANAL_ONEDRIVE.md`; se confirman en la primera prueba real (paso 8 de la guía).

## D. Panel de gastos — pestaña «Eventos» (análisis de satisfacción y tiempos)

**Quién la ve:** solo `admin` y `super_admin` (`require_role("admin")`). **Dónde:** `/gastos` → pestaña «Eventos». **Código:** `app/event_analytics.py` (cálculo puro, sin base), `app/routers/gastos_eventos.py` (API), `templates/_gastos_eventos.html`, `static/js/gastos-eventos.js`, `static/css/gastos-eventos.css`. **Pruebas:** `tests/test_analitica_eventos.py`. **Sin migración:** todo sale de tablas que ya existen.

### API (todas GET, solo admin, caché en memoria de 60 s por combinación de filtros)
`/api/gastos/eventos/` + `panel` (todo junto; es lo que usa la pantalla) · `resumen` · `satisfaccion` · `tiempos` · `alertas` · `filtros` (clientes y comerciales para los selectores) · `exportar` (Excel).
Filtros: `desde`, `hasta` (AAAA-MM-DD; por defecto los últimos 12 meses; se filtra por la fecha de FIN del evento), `cliente` (id), `comercial` (id de cuenta), y umbrales de alertas `low` (1-3), `overdue` y `wait` (días).

### Qué eventos cuentan
Eventos cuyo `end_date` cae en el rango. **Se excluyen** los de prueba: código que empieza por `LOAD-` (pruebas de carga). `Event` no tiene bandera «de prueba»; si algún día se agrega, se cambia `TEST_EVENT_PREFIXES`/`load_events` en un solo lugar. No se cuentan asistentes, así que la persona `PRUEBA` no interviene. Los archivados SÍ cuentan (siguen siendo historia).

### Fórmulas
- **Calidad (1-3):** Malo = 1, Bueno = 2, Excelente = 3 (`survey_def.RATING_SCORES`); «No aplica» no puntúa. Promedio por pregunta = media de los puntajes de esa pregunta. Promedio de un evento = `survey_responses.avg_score`.
- **NPS:** `%promotores (9-10) − %detractores (0-6)` sobre las respuestas a «¿recomendaría?» (0-10); los 7-8 son neutros. Resultado de −100 a 100, redondeado a entero. Sin respuestas → «—».
- **Tasa de respuesta:** encuestas respondidas ÷ eventos «entregados» (tienen enlace de entrega o están facturados) × 100.
- **Quieren otro evento:** respuestas «Sí» ÷ (Sí + No) de la pregunta `q8_next_event`. **Ya crearon uno:** de los «Sí», cuántos clientes crearon un evento con `created_at` posterior a su respuesta (inferido; es un cálculo, no un dato registrado).
- **Evolución mensual:** por mes en que se contestó la encuesta, promedio de calidad y NPS.
- **Mejor/peor evaluados:** top 5 por promedio de calidad (desempata por recomendación). **Por comercial / coordinador / cliente / ciudad:** promedio de calidad y NPS de los eventos de cada grupo, de mejor a peor.
- **Tiempos (días, con decimales):** `fin del evento` = el final del día `end_date`.
  - Cerrar = `finalized_at − fin`. Subir la base = `final_db_uploaded_at − fin`. Facturar = `billed_at − finalized_at` y `billed_at − fin`.
  - Por cada etapa: n, promedio, **mediana** (la mitad tarda menos) y **P90** (9 de cada 10 tardan menos), con interpolación lineal. Una duración negativa o con fecha faltante no entra (no rompe el promedio).
  - Mensual = por mes del fin del evento. Por comercial/cliente: mismas estadísticas, ordenado del que más tarda en facturar al que menos.
- **Resumen en lenguaje claro:** «Este mes: NPS +X, N encuestas respondidas, N eventos facturados, tiempo promedio de facturación D días». «Este mes» = mes local actual; NPS y encuestas del mes de respuesta; eventos facturados del mes de `billed_at` dentro del filtro; días = promedio fin → facturado de esos eventos.

### Alertas (umbrales configurables en la pantalla, «Umbrales de las alertas»)
- **Baja satisfacción:** promedio ≤ `low` (por defecto 1,8) o recomendación de detractor (0-6).
- **Atrasados sin facturar:** Finalizados hace más de `overdue` días (30) sin `billed_at`; enlaza al evento.
- **Encuestas sin responder:** Facturados hace más de `wait` días (7) sin encuesta; indica si el cliente abrió el enlace.
- **Clientes a la baja:** la última encuesta del cliente quedó ≥ 0,3 por debajo de la anterior (necesita 2 o más).

### Privacidad
Solo eventos, clientes y cuentas del personal; ningún dato de asistentes. Los comentarios son texto libre del cliente (la encuesta no pide ni guarda quién responde) y solo los ve el administrador; se muestran con `textContent`. El Excel pasa por `xlsafe.safe_workbook`. Nada de esto se escribe en logs ni toca la base con frecuencia: se calcula cuando un administrador abre o filtra la pestaña.

### Gráficos
SVG propio (barras horizontales, columnas 0-10, líneas mensuales), sin librerías ni costo; colores con tokens `--gw-*` (claro/oscuro) y cada barra/punto con `<title>` y su valor escrito; junto a cada gráfico hay tabla o cifras.

## C. Panel de gastos — pestaña «Infraestructura» (hecha, sin probar en la nube)

Pantalla `/gastos` (solo admin y super_admin; el enlace «Gastos» del menú solo lo ven ellos). Tiene dos pestañas: «Infraestructura» (esta pieza) y «Eventos» (pieza D, se incluye con `_gastos_eventos.html` y `gastos-eventos.js`; la carcasa dispara el evento `gastos:tab` al cambiar de pestaña).

**Qué muestra:** total del periodo, promedio por mes, promedio por evento, barras apiladas por mes y proveedor (Google Cloud, Neon, Microsoft, Cloudflare, Otros), tendencia del total, barras de costo por evento (parte fija y variable), tabla de gastos y descarga de Excel (hojas «Gastos», «Por evento», «Por mes», con protección contra fórmulas de Excel). Gráficos propios en SVG, sin librerías ni CDN, con tooltip, leyenda, vista como tabla y modo oscuro; colores validados para daltonismo con el validador de paletas.

**De dónde salen los datos**
1. **Registro manual** (siempre disponible): proveedor, mes, concepto, tipo (fijo o variable), moneda COP/USD con la TRM del día guardada en el registro (el histórico no cambia si el dólar se mueve), nota y soporte opcional (PDF/PNG/JPG ≤ 5 MB, por `app/storage.py`). Cada alta, cambio, borrado y adjunto queda en `audit_actions`.
2. **Importación automática de Google (opcional):** solo si existe `GCP_BILLING_EXPORT_TABLE` (`proyecto.conjunto.tabla`). Una vez al mes (día `OPS_INFRA_DAY`=2, hora `OPS_INFRA_HOUR`=6, hora local) el Job de ops (paso `infra-costs`; a mano: tarea `infra-costs-import` o el botón «Importar Google ahora») lee el costo NETO (costo + créditos) del mes en curso y del anterior por servicio y lo guarda como gasto `gcp_export`. Es idempotente (clave `gcp:AAAA-MM:servicio`) y no pisa lo registrado a mano; un gasto importado que se edita pasa a manual. En USD usa la «TRM por defecto» del panel (sin ella omite la fila con aviso). No consulta nada de seguido (Neon puede apagarse). Usa la API REST de BigQuery (`jobs.query` + `getQueryResults`, con paginación y tope de 50 s) autenticada con `google.auth` (ya viene con `google-cloud-storage`): NO hace falta `google-cloud-bigquery`. El nombre de la tabla se valida con una expresión estricta `proyecto.conjunto.tabla` antes de interpolarlo; el mes va como parámetro `@ym`. La cuenta de servicio del Job de operaciones necesita `roles/bigquery.jobUser` en el proyecto de la tabla (p. ej. `goldenweb-prod`) y `roles/bigquery.dataViewer` sobre el conjunto `billing_export` (los da Juan David).
3. **Neon:** verificado en la documentación oficial (`GET /consumption_history/v2/projects`, plan Launch o superior, histórico mensual del último año): esa API entrega CONSUMO (segundos de cómputo, bytes), no dinero. Por eso el costo de Neon se registra a mano; con `NEON_API_KEY` y `NEON_ORG_ID` la pantalla muestra además las horas de cómputo del mes (informativo; falla en silencio).

**Reparto por evento (también visible en pantalla, parámetro editable «Criterio de reparto»)**
- Costos **variables** (Cloud Run, Storage, Neon…): `costo del mes × ingresos del evento en el mes ÷ ingresos de todos los eventos del mes` (tabla `access_logs`, hora de Colombia, sin la persona de prueba).
- Costos **fijos** (dominio, Microsoft 365, GitHub, Cloudflare…): `costo del mes × días del evento dentro del mes ÷ suma de días de todos los eventos del mes` (eventos con fecha de inicio y que no estén en «creado»).
- Criterios: `auto` (lo anterior, por defecto), `activity` (todo por ingresos), `days` (todo por días). Si el criterio no tiene datos ese mes se prueba el otro; si ninguno, el costo queda «sin asignar» y se muestra así. Los centavos del redondeo van al último evento: el reparto siempre suma el total. No hay datos de peticiones por evento, así que la actividad es solo ingresos registrados.
- Promedio por evento = costo repartido ÷ eventos con costo.

**Pasos de Juan David**
1. Aplicar la migración `0121_infra_costs` (cadena: tras `0119_system_alerts`; verificar que no haya una 0120 pendiente) — solo con su autorización, igual que cualquier migración.
2. Registrar los gastos de cada proveedor en `/gastos` (mensual).
3. Para Google automático (opcional): en la consola de Facturación → «Exportación de facturación» → activar la **exportación estándar a BigQuery** (crear un conjunto de datos). Solo trae datos desde que se activa (y, en ubicación multirregional, desde el mes anterior); lo anterior se registra a mano. Luego poner `GCP_BILLING_EXPORT_TABLE=proyecto.conjunto.gcp_billing_export_v1_XXXXXX` en el Job de ops y dar a la cuenta de servicio del Job `roles/bigquery.jobUser` (proyecto) y `roles/bigquery.dataViewer` (conjunto `billing_export`).
4. Para ver el uso de Neon (opcional): crear `NEON_API_KEY` en Secret Manager y poner `NEON_ORG_ID`.

**Pruebas:** `tests/test_gastos_infra.py` (validación, moneda, reparto, importación con consulta simulada, permisos, CRUD con auditoría y adjuntos, Excel). No se pudieron correr en el entorno de la pieza (sin base): solo `py_compile`, `ruff`, `node --check`, y la lógica pura se ejecutó a mano; los gráficos se revisaron en un navegador con datos de ejemplo (escritorio, celular, oscuro).

