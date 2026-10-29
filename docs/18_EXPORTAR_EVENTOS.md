# 18 · Exportar e importar eventos (diseño e inventario)

Rama `producto/exportar-evento` (cortada de `main` = `6c71cc3`, 28-oct-2026). Estado: **F0–F5 hechas** (28-oct-2026): motor (`app/event_transfer.py`), trabajos en segundo plano (`app/event_transfer_jobs.py`), endpoints (`app/routers/event_transfer.py`, solo super_admin), interfaz (`static/js/event-transfer.js`), scripts `scripts/event_export.py` y `scripts/event_import.py`, y migraciones `0074_event_transfer` y `0075_transfer_jobs` (aditivas).
Objetivo: sacar un evento COMPLETO de un entorno (staging, producción o servidor local) y crearlo en otro quedando igual: configuración, parámetros, campos, plantilla de escarapela, ajustes de impresión, formularios, ruleta, personas, registros con sus horas y resultados.
Reglas que mandan sobre todo lo de abajo: `CLAUDE.md` (endpoints `def`, archivos solo por `app/storage.py`, lo largo por `app/jobs.py` o Cloud Run Job, nada de datos personales en logs, horas en UTC, compatible con el pooler de Neon, revision Alembic ≤ 32 caracteres) y la regla legal de biometría (L1–L4).

## 1. Inventario: lo que cuelga de un evento

Sacado de `app/models.py` (50 tablas; **27 con `event_id` o FK a `events`**, 5 más cuelgan de un formulario, 18 no cuelgan del evento) y de las claves de `app/storage.py`. Columna «Clase»: **C** se copia tal cual (con mapa de ids) · **R** se recalcula en el destino · **X** se EXCLUYE.

### 1.1 Tablas del evento

| Tabla | Qué es | Clase | Notas / por qué |
|---|---|---|---|
| `events` | el evento: código, nombre, fechas, estado, parámetros (puerta, facial, logo, categorías, impresión `print_settings_json`, `shared_print_enabled`, `auto_register`, `controller_mode`…) | **C** | Siempre se crea un evento NUEVO. `id` nuevo; `event_code` y nombre se piden de nuevo si ya existen; `certificates_token` se conserva si está libre (si no, se genera uno nuevo y se avisa). `coordinator_staff_id`, `commercial_staff_id`, `created_by_id` → por nombre de usuario (§2.3). `super_event_id` y `state_id` → por nombre. `logo_path`, `report_pdf_path` → archivos (§1.2). `faces_version` → R (vuelve a 0/1 y se reconstruye). `biometrics_purged_at`, `finalized_at`, `created_at` → tal cual (la retención sigue contando con las fechas ORIGINALES). |
| `event_field_configs` | campos opcionales del evento (`opcional_N`, tipo, obligatorio, estadística, orden) | **C** | `event_id` remapeado. `field_key` se conserva (las personas y la plantilla lo usan). |
| `event_areas` | áreas del evento | **C** | id nuevo; lo usa `area_movements`. |
| `inventory_items` | ítems de inventario | **C** | id nuevo; lo usa `inventory_deliveries`. |
| `badge_templates` | plantilla de escarapela por categoría/tipo (`elements_json`, fondo) | **C** | `imported_from_saved_template_id` → NULL (la biblioteca guardada del cliente no viaja). Imágenes del fondo/logos → `badge_assets` (§1.2). |
| `web_forms` | formularios web del evento (diseño, ajustes, cupo, calendario) | **C** | Reutiliza el formato de `app/routers/form_transfer.py` para diseño y ajustes; `slug` se conserva si está libre (único por evento). `test_key` se regenera (clave de pruebas: nunca se copia). Quedan en estado `pruebas` si el paquete no dice otra cosa. |
| `form_submissions` | respuestas (inscripciones) | **C** | `person_id` = cédula (se conserva). `invite_id`, `discount_code_id`, `form_id` remapeados. `source` = `importado`. |
| `form_payments` | pagos (Wompi) | **C** | **Registro histórico**: no crea pagos nuevos ni toca Wompi. Columna nueva `origin='importado'` (migración 0074, §2.6). `reference` es única: si ya existe en el destino se omite el pago y se avisa. |
| `form_refunds` | reembolsos | **C** | Historia; `payment_id` remapeado; no se vuelve a ejecutar nada (`status` se conserva). |
| `form_discount_codes`, `form_invites`, `form_people`, `form_events` | códigos de descuento, invitaciones, pre-llenado y embudo (estadísticas del formulario) | **C** | `form_invites.token` se conserva si está libre (si no, nuevo y se avisa); `sent_at/used_at` tal cual: **no se reenvía ningún correo**. |
| `roulette_configs` | ruleta: comportamiento, estilo, `display_token` | **C** | `display_token` conservado si está libre. `authorized_json` (autorización de un sorteo en curso: lleva el id de quien autorizó) → NULL. |
| `roulette_draws` | sorteos hechos y ganadores (`winners_json` lleva cédulas y nombres) | **C** | Contiene datos personales: viaja solo en el paquete cifrado en tránsito (§2.5/2.6). `created_by_id` → usuario por nombre. |
| `event_attendees` | personas inscritas al evento (categorías, `origin`, tokens digitales y de aceptación) | **C** | `UNIQUE(event_id, user_id)`; `digital_token` y `accept_token` conservados si están libres. `origin` tal cual (base / manual / autoregistro / importado). |
| `users` (persona por cliente, PK cédula+cliente) | datos de la persona: nombre, empresa, contacto, `opt_1…`, `extra_fields`, `birth_date` | **C** | Solo las personas del evento. Si la persona **ya existe** en el destino (otro evento del mismo cliente) NO se sobrescribe: se conserva lo del destino y las diferencias salen en el simulacro. Campos biométricos (`face_encoding`, `face_captured_at`, `is_biometric_enabled`, `biometric_consent_*`) → **X por defecto** (§2.5). |
| `access_logs` | registros / acreditaciones con hora (`timestamp`, `record_type`, `client_id`, método, quién registró) | **C** | Horas en UTC sin convertir. `registered_by_staff_id` → nombre de usuario (§2.3). `client_id` se conserva (es la llave de idempotencia de la cola sin conexión). |
| `area_movements` | entradas/salidas por área | **C** | `area_id` remapeado. |
| `inventory_deliveries` | entregas de inventario | **C** | `item_id` remapeado. |
| `print_logs` | reimpresiones de escarapela | **C** | historia; `printed_by_staff_id` → usuario por nombre. |
| `person_changes` | historial de cambios por persona | **C** | historia/auditoría; `staff_user_id` → usuario por nombre. |
| `audit_consent_logs` | consentimientos (solo INSERT, 3 años) | **C** | Se copian TAL CUAL, con su fecha original, solo INSERT, `id` conservado (es texto/UUID); si ya existe ese `id` se salta. Sin consentimiento aceptado no hay reconocimiento facial en el destino (regla existente). |
| `web_acceptances` | aceptaciones por el enlace web | **C** | evidencia de consentimiento; `verified_by_staff_id` → usuario por nombre. |
| `event_documents`, `event_expenses` | documentos y gastos con archivo adjunto | **C** + archivos | `stored_path` / `evidence_path` → archivos (§1.2); `uploaded_by_id`/`created_by_id` por nombre. |
| `event_staff_authorizations` | qué personal está autorizado en el evento | **X** | Es personal del entorno de origen (no se copian cuentas). Se anotan los nombres de usuario en el manifest para que el destino los autorice a mano. |
| `print_devices`, `print_routes`, `print_stations`, `print_jobs` | estado EN VIVO de la impresión compartida (equipos, rutas, puestos, cola) | **X** | Son efímeros y apuntan a cuentas del entorno. La **configuración** de impresión viaja en `events.print_settings_json`; la plantilla en `badge_templates`. |
| `bulk_jobs` | historial de cargas masivas | **X** | Operativo; su efecto (las personas) ya viaja en `event_attendees`/`users`. |
| `privacy_requests` | solicitudes de privacidad (radicados, titular) | **X** | Registro legal del titular: se queda donde se radicó; no se multiplica entre entornos. |
| `accept_mail_log` | bitácora de envíos de correo de aceptación | **X** | Operativa y recalculable; copiarla sugeriría que el destino envió correos. |

### 1.2 Archivos (`app/storage.py`; las claves son relativas, con el cliente como primer trozo)

| Clave | Qué es | Clase | Notas |
|---|---|---|---|
| `<cliente>/badge_assets/<archivo>` | fondos y logos de plantillas, imágenes de formularios y de la ruleta | **C** | Solo los que el evento referencia (en `badge_templates.elements_json`/`background_value`, `web_forms.design_json`/`settings_json`, `roulette_configs.style_json`, `events.logo_path`). Se renombran por contenido (SHA-256) para no pisar los del destino. |
| `<cliente>/form_files/<form_id>/<archivo>` | archivos subidos en respuestas de formularios | **C** | el `<form_id>` se remapea; la respuesta guarda el nombre del archivo. |
| `<cliente>/signatures/<event_id>/<cédula>__<campo>.png` | firmas de personas | **C** | datos personales: solo en paquete cifrado en tránsito. |
| `<cliente>/event_docs/<event_id>/…`, `event_expenses/<event_id>/…` | documentos y evidencias de gasto | **C** | |
| `events.logo_path`, `events.report_pdf_path` | logo del evento e informe PDF final | **C** | |
| `[biometric/]<cliente>/known_people/<cédula>.jpg` | foto de registro (biométrica, cifrada en reposo con `FACE_ENCRYPTION_KEY`) | **X por defecto** | Solo con «incluir biometría» (§2.5). |
| `outbox/*.eml`, `bulk_steps/*`, `report_jobs/*`, copias de `ops` | temporales y bitácoras operativas | **X** | |
| fuentes de la escarapela | `static/fonts/` (parte del código, no del storage) | **—** | La plantilla las nombra; el destino ya las trae (mismo código). El importador avisa si la plantilla usa una tipografía que el destino no tiene. |

### 1.3 Lo que NO cuelga del evento (no se exporta)

`staff_users` (cuentas, contraseñas, sesiones), `tenants` (se crea el cliente si no existe, solo con nombre y código), `event_states` y `super_events` (se enlazan por NOMBRE; si no existen en el destino queda sin enlace y se avisa), `saved_badge_templates`, `saved_form_templates`, `saved_colors` (biblioteca del cliente), `suppressed_people` (**no se exporta, pero se CONSULTA al importar**: una persona suprimida en el destino no se vuelve a crear), `jobs`, `rate_limit_events`, `system_events`, `session_audit`, `app_settings`, `password_reset_tokens`, `privacy_request_counters`, `calendar_notes`.

### 1.4 Estadísticas derivadas

No hay tablas de estadísticas: `app/routers/analytics.py`, `stats.py` y `event_report.py` las calculan al vuelo desde `access_logs`, `event_attendees`, `area_movements`, `form_*`, etc. → **R**. Que el evento importado dé las mismas cifras es justamente la prueba de fidelidad (§2.7). Lo que sí se recalcula tras importar: la matriz de reconocimiento (por tarea) y `faces_version`.

## 2. Diseño (decisiones tomadas, con su porqué)

### 2.1 Formato del paquete
Un `.zip` con:
- `manifest.json`: `format` = `goldenweb-evento`, `format_version`, `alembic_revision` de origen, `source_env` (`staging`/`production`/`local`), `created_at` (UTC), `tenant` (código y nombre del cliente), conteos por tabla, lista de archivos con su **SHA-256**, usuarios del personal citados (solo nombres), opciones (`include_biometrics`), y una huella por tabla (suma de control sobre las filas ordenadas).
- `data/<tabla>.jsonl`: una fila por línea, con los ids de ORIGEN (se remapean al importar). Horas en ISO-8601 UTC.
- `files/<clave relativa>`: archivos del storage.
- `LEEME.txt` (qué contiene, que lleva datos personales).

Se reutiliza el patrón de `form_transfer.py`: nombre de formato + `version`, lista blanca de nombres de entrada (`NAME_RE`), topes (entradas, bytes descomprimidos contra «zip bomb», tamaño por archivo) y «todo o nada». Los límites se suben (un evento es más grande que un formulario) y se leen de variables, no del código.
**Compatibilidad:** el importador **rechaza** un paquete cuyo `format_version` o cuya revisión de Alembic de origen sea MÁS NUEVA que la del destino, con un mensaje claro («actualiza el destino a la versión X»). Uno más viejo se acepta (las columnas que falten se rellenan con su valor por defecto).

### 2.2 Ids
Los ids numéricos cambian entre entornos. El importador procesa las tablas en **orden topológico** (evento → campos/áreas/ítems/plantillas/formularios → formulario hijos → personas → registros) y mantiene un **mapa origen→destino por tabla**. Se conservan los identificadores de negocio: `event_code` (o uno nuevo si choca), cédulas, `client_id` de los registros, tokens, slugs, referencias de pago, `audit_consent_logs.id`. Las horas se copian en UTC sin convertir.

### 2.3 Personal (cuentas)
Las cuentas NO se copian y nunca se crean cuentas ni contraseñas. Donde una fila guarda «quién lo hizo» (`registered_by_staff_id`, `printed_by_staff_id`, `staff_user_id`, `coordinator_staff_id`…), el export lo convierte a **nombre de usuario** (`@names` en la fila). En el destino: si existe un usuario con ese nombre, se enlaza; si no, el enlace queda NULL y el **texto se conserva** en la tabla `event_import_actors` (migración 0074: importación, tabla, fila, columna y nombre). *Decisión de F1:* una tabla aparte en vez de agregar columnas de nombre a `access_logs` y demás, para no alterar tablas grandes y calientes. El nombre de usuario no es un dato sensible del titular; no se copia nada más del personal.

### 2.4 Importar SIEMPRE crea un evento NUEVO
Nunca sobrescribe. Si el código o nombre ya existe, el asistente pide uno nuevo. Pasos: **1) simulacro** (dry-run: no escribe nada; lista qué entraría, conteos, conflictos —código/nombre, personas ya existentes con datos distintos, tokens o referencias que chocan, usuarios del personal sin enlace, tipografías ausentes, personas suprimidas que se omiten, estados/super-eventos sin equivalente—) y **2) importar de verdad**. **Una transacción por evento**, con SAVEPOINT por lote en cargas grandes. **Idempotente:** el importador anota en una tabla de control (`event_imports`, migración 0074) la huella del paquete y el evento creado; reintentar tras un corte retoma o responde «ya importado», y no duplica personas, registros ni consentimientos.

### 2.4b Estado al importar (ajustes del 28-oct-2026)
- Los **formularios** entran en «pruebas» (sin calendario). Opción del asistente **«conservar el estado original»** (apagada por defecto, con aviso): el estado y calendario originales quedan guardados y se aplican solo al **confirmar**.
- Un evento **finalizado** o **creado** entra tal cual y sin efectos. Un evento **en proceso** entra en espera (estado «creado») hasta que se **confirma** la importación (`POST /api/event-transfer/imports/{n}/confirm` o `--confirm N`): mientras tanto **no activa el congelamiento de despliegues**. Importar no dispara cierres automáticos, purgas ni correos.

### 2.5 Biometría y privacidad (regla legal, no negociable)
- **Por defecto NO se exporta** ningún rostro, foto de registro, encoding ni vector: se anulan `users.face_encoding`, `face_captured_at`, `biometric_consent_at`, `biometric_consent_source`, `is_biometric_enabled=false` y no se copian las fotos.
- Opción explícita **«incluir biometría»**: solo `super_admin`, apagada por defecto, con aviso. Si se incluye: los archivos biométricos y los vectores van **cifrados con una clave de transporte** (frase que escribe quien exporta y que NO se guarda; derivada con PBKDF2-HMAC-SHA256 + Fernet, el mismo algoritmo de `app/crypto.py`), y el destino los **vuelve a cifrar con SU `FACE_ENCRYPTION_KEY`** (la de cada entorno es distinta).
- Los consentimientos (`audit_consent_logs`) se copian tal cual y solo INSERT. Sin consentimiento aceptado en el destino no hay reconocimiento facial (regla existente de `app/faces.py`).
- **La retención** (7 días tras finalizar todos los eventos de la persona; tope de 180 días desde la captura) sigue contando con las fechas ORIGINALES (`face_captured_at`, `finalized_at`). `app/minors.py`: los menores se importan SIN biometría aunque el paquete la traiga.
- Tras importar con biometría, la matriz de reconocimiento se reconstruye **por tarea** (`app/enroll.py` / `app/faces.py`), nunca dentro de la petición.
- Personas **suprimidas** en el destino (`suppressed_people`) no se importan.

### 2.6 Sin efectos secundarios
Importar **no** envía correos, **no** llama a Wompi ni dispara webhooks, **no** encola trabajos de reconocimiento ni notificaciones y **no** crea pagos nuevos. Los pagos y respuestas se copian como registros históricos con `origin='importado'` (columna nueva `form_payments.origin`, migración 0074; en `form_submissions` se usa la columna `source` que ya existe). Las banderas de «ya enviado» (`digital_sent_at`, `accept_sent_at`, `sent_at`) se copian tal cual para que el destino NO reenvíe. Los formularios importados quedan en estado «pruebas».
**Migración 0074** (escrita a mano, aditiva, id de 19 caracteres: `0074_event_transfer`): tablas `event_transfer_log` (bitácora; guarda el estado en espera de una importación) y `event_import_actors` (nombres de usuario sin cuenta, §2.3), y la columna `form_payments.origin`. Probada sobre una copia de la base de demostración (subir, comprobar, bajar y volver a subir; los conteos de las tablas previas no cambian). Nada toca datos existentes.

### 2.7 Seguridad, tamaño y archivos
- Solo **`super_admin`** exporta e importa. Bitácora en `event_transfer_log`: quién, cuándo, evento, conteos, opciones, huella; **sin datos personales** y nunca el contenido del paquete en logs.
- El `.zip` contiene datos personales: se genera en el storage bajo `transfers/<cliente>/…`, se sirve por **URL firmada de vida corta** (`app/uploads.py`; en local, por `PUT/GET` firmado), y el **paso `purge` del Job de ops lo borra a las 24 h**.
- Lo largo (exportar/importar un evento de miles de personas) corre en **Cloud Run Job / `app/jobs.py`** con progreso, como `bulk_jobs` (el límite de 60 s de Firebase Hosting aplica a cada petición, no al trabajo). La subida del paquete al importar es directa al storage con `app/uploads.py`.
- Los mismos módulos sirven a la interfaz, a los Jobs y a los scripts `scripts/event_export.py` y `scripts/event_import.py` (**mismo código**, para el servidor local y para Cloud Run Jobs).

### 2.8 Verificación de fidelidad
Tras importar, el sistema compara **conteos y sumas de control por tabla** contra el manifest y muestra el informe «Origen vs Destino» (iguales / diferencias, con la razón de cada diferencia esperada: tablas excluidas, filas omitidas por conflicto o supresión). **Prueba de oro (F5):** exportar un evento sintético completo, importarlo en una base de pruebas vacía, volver a exportarlo, y comprobar que los dos paquetes son equivalentes salvo ids y metadatos (fecha, entorno, huellas de ids).

### 2.9 Interfaz
En la ficha del evento (Parámetros), botones «Exportar evento» e «Importar evento» con asistente paso a paso: opciones → (si es biometría: aviso y frase) → generar → descargar; importar: subir → simulacro → nombre nuevo si hay conflicto → «Importar de verdad» → informe. `showToast`/`showConfirm` de `toast.js`, sin `onclick` inline, `url_for('static', …)`, textos en español.

### 2.10 Modo local (diseño, no se construye ahora)
`docs/17_SERVIDOR_LOCAL.md`: el servidor local importa el mismo paquete, opera sin internet y exporta **«solo lo nuevo»**. El formato ya lo permite: el manifest lleva `since` (marca UTC) y cada fila de registros trae su `client_id`/`id` de negocio; el paquete «de vuelta» contiene solo `access_logs`, `area_movements`, `inventory_deliveries`, `print_logs`, `person_changes`, `audit_consent_logs`, `web_acceptances` y las personas/inscripciones nuevas desde `since`, y el importador de la nube los **fusiona** con el evento original (mapa por `event_code` + `import_id`; los `client_id` hacen la fusión idempotente). Los scripts de línea de comandos (`--since`) quedan preparados en F4; la fusión («importar sobre el MISMO evento sin sobrescribir») es trabajo del modo local.

## 3. Plan por fases

| Fase | Entrega |
|---|---|
| **F0** | este documento (inventario + diseño) |
| **F1** | exportar/importar SIN biometría y sin archivos pesados: config, campos, áreas, plantilla (JSON), formularios, ruleta, personas, registros, consentimientos; migración 0074; simulacro; idempotencia; mapa de ids; sin efectos secundarios |
| **F2** | archivos del storage (plantilla, imágenes del evento y de formularios, firmas, documentos, informe) con SHA-256 |
| **F3** | biometría opcional cifrada con frase de transporte |
| **F4** | interfaz (asistente), bitácora, URL firmada, borrado a las 24 h, Cloud Run Job con progreso, scripts CLI |
| **F5** | informe «Origen vs Destino» y prueba de oro |

Pruebas: `pytest` con datos **sintéticos** en `golden_test` (nunca datos reales; el evento 20 real de staging NO se toca: el caso de prueba usa un evento sintético equivalente).

## 4. Cómo se usa (F4)

**Interfaz (solo `super_admin`):**
- **Exportar:** en «Clientes» (dentro de cada cliente, en la fila de cada evento) y en «Eventos» (en cada tarjeta) hay un botón **📦 Exportar**. El asistente ofrece incluir biometría (apagado por defecto; pide una frase de transporte de 8+ caracteres que NO se guarda), genera el paquete en segundo plano con barra de avance y entrega un enlace de descarga firmado que dura 5 minutos. El `.zip` se borra del servidor a las 24 h.
- **Importar:** en «Clientes», cada cliente tiene **📥 Importar evento** (el cliente ya viene elegido); en «Eventos» hay uno general donde se elige el cliente. Pasos: subir el paquete (subida directa) → revisión → código y nombre del evento nuevo, «conservar el estado original» (apagada, con aviso) y, si el paquete trae biometría, su frase → **simulacro** (no escribe nada: conteos, omitidas, personas nuevas/existentes/suprimidas, archivos, avisos) → **importar de verdad** → informe **«Origen vs Destino»** → **confirmar** el estado si el evento quedó en espera. Todo queda en la bitácora (quién, cuándo, evento y filas; sin datos personales).

**Endpoints:** `POST /api/event-transfer/export/start`, `GET …/jobs/{n}`, `GET …/download/{n}?t=`, `POST …/upload-url`, `POST …/import/inspect`, `POST …/import/start` (`dry_run` true/false), `POST …/imports/{n}/confirm`, `GET …/log`; y los de un paso de F1 (`export/{id}`, `import/dry-run`, `import`) para scripts y pruebas.

**Línea de comandos:** `python scripts/event_export.py --event-code X --out evento.zip` y `python scripts/event_import.py evento.zip --new-code Y --new-name "…" [--dry-run]` (mismo motor).

## 5. Verificación realizada

- **Pruebas** (`tests/test_event_transfer.py`, 28): exportar (huellas, sin biometría ni cuentas), simulacro que no deja nada, importar creando un evento nuevo, no sobrescribir, personas existentes y suprimidas, personal sin cuenta, sin efectos secundarios, pagos históricos, evento en espera y congelamiento, archivos (misma imagen reutilizada, otra distinta con otro nombre, fallo a medias sin huérfanos), importar a otro cliente, biometría (frase, solo adultos con consentimiento, re-cifrado con la llave del destino), descarga firmada y borrado a las 24 h, flujo completo del asistente y la **prueba de oro** (exportar → importar en base vacía → exportar: paquetes equivalentes y archivos byte a byte iguales).
- **Navegador** (base de demostración con 8 000 personas sintéticas): exportar, subir, simulacro e importar tardan 1–2 s cada uno; origen y destino iguales.
- **Migraciones 0074 y 0075:** probadas bajando y subiendo sobre una copia con datos sintéticos; los conteos de las tablas previas no cambian.

## 6. Límites conocidos

- Un solo evento por paquete. El paquete se arma en memoria del servicio (límite por archivo 100 MB y 512 MB por paquete, configurables con `EVENT_TRANSFER_MAX_FILE_MB` y `EVENT_TRANSFER_MAX_ZIP_MB`).
- La importación sobre el MISMO evento («solo lo nuevo» del modo local, §2.10) sigue como diseño; no se construyó.
- Una persona que ya existe en el destino no se actualiza (se informa cuántas difieren).
