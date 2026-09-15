# Casos de Prueba — Golden Biometrics

Checklist manual de validación funcional. No hay suite automatizada (`pytest`) todavía — ver
backlog en `CLAUDE.md` — así que esto se ejecuta a mano contra una instancia local
(`uvicorn app.main:app --reload --port 5000`) con una base de datos de prueba.

Cada caso tiene: **Precondición**, **Pasos** (la secuencia exacta a seguir) y **Resultado
esperado**. Los casos marcados ✅ son el **camino correcto** (verifican que la función
funciona); los marcados ❌ son **casos de validación/error** (verifican que el sistema
efectivamente bloquea, avisa o corrige lo que debe — si en vez de eso el sistema deja pasar
el caso incorrecto, es un bug).

Si algún caso falla, revisa la sección correspondiente de `CLAUDE.md` (documenta el
comportamiento esperado y por qué) antes de asumir que es un bug nuevo.

## 0. Preparación del entorno de prueba

1. `alembic upgrade head` (asegura que las migraciones `0001`–`0011` estén aplicadas).
2. Si no existe ninguna cuenta todavía: `python scripts/create_staff_user.py --username super --role super_admin --full-name "Super Admin"` (pide contraseña la primera vez que se usa, ver `scripts/create_staff_user.py`).
3. `uvicorn app.main:app --reload --port 5000`.
4. Con la sesión de `super_admin`, crear al menos:
   - Un **coordinador** (`/admin/staff`, formulario "Nueva cuenta").
   - Un **cliente** (Tenant) vía `/` → "Nuevo cliente" (ej. `name="Corferias"`).
   - Un **evento** para ese cliente, con un `coordinator_staff_id` válido.
   - Dentro de ese evento (pestaña "Usuarios del Evento"): una cuenta `digitador` y una `cliente`.
5. Ten a mano un teléfono/webcam para las pruebas de reconocimiento facial (o una foto de rostro guardada para subir como archivo).

Cuentas necesarias para cubrir todos los casos: `super_admin`, `admin`, `coordinador`, `digitador`, `cliente`.

---

## 1. Autenticación y sesión (`/login`, `/logout`)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| AUTH-01 ✅ | Login correcto | Ir a `/login`, ingresar usuario/contraseña válidos, enviar | Redirige a `/` (dashboard según rol), cookie de sesión (`Set-Cookie`) presente |
| AUTH-02 ❌ | Contraseña incorrecta | `/login` con usuario válido + contraseña equivocada | Mensaje de error en pantalla, **no** crea sesión, sigue en `/login` |
| AUTH-03 ❌ | Usuario inexistente | `/login` con un usuario que no existe | Mismo mensaje genérico que AUTH-02 (no debe distinguir "usuario no existe" de "contraseña mala" — evita enumeración de usuarios) |
| AUTH-04 ❌ | Cuenta desactivada | Desactivar una cuenta (`admin`+ vía `/admin/staff`) e intentar loguearse con ella | Login rechazado igual que credenciales inválidas |
| AUTH-05 ❌ | Acceder sin sesión | Sin loguearse, ir directo a `/`, `/kiosk/1`, `/admin/staff` | Redirige a `/login` en los tres casos |
| AUTH-06 ❌ | API sin sesión | Sin loguearse, `curl http://localhost:5000/api/users?event_id=1` | 401/403 (no data expuesta) |
| AUTH-07 ✅ | Logout | Logueado, clic en "Salir" | Vuelve a `/login`; reintentar `/` sin volver a loguearse debe redirigir a `/login` (sesión realmente invalidada) |
| AUTH-08 ❌ | `/docs` en producción | Con `ENVIRONMENT=production` en `.env`, ir a `/docs`, `/redoc`, `/openapi.json` | 404 en los tres (en `development` deben SÍ abrir, ver `main.py`) |

---

## 2. Roles y jerarquía de permisos

Jerarquía: `cliente` (fuera de la jerarquía real, ver `CLAUDE.md`) < `digitador` < `coordinador` < `admin` < `super_admin`.

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROLES-01 ✅ | Coordinador crea digitador/cliente en un evento | Logueado como `coordinador`, entrar a un evento → "Usuarios del Evento" → crear cuenta rol `digitador` | Se crea y queda autorizada para ese evento |
| ROLES-02 ❌ | Coordinador intenta crear `cliente` | Mismo formulario, elegir rol `cliente` como `coordinador` | 403 "Solo un Admin puede crear cuentas cliente" |
| ROLES-03 ✅ | Admin crea `cliente` | Repetir ROLES-02 logueado como `admin` | Se crea correctamente |
| ROLES-04 ❌ | Crear `digitador`/`cliente` desde `/admin/staff` | Como `admin`, en `/admin/staff` intentar crear rol `digitador` | 400 "se crean desde dentro de un evento" |
| ROLES-05 ❌ | Admin crea otro Admin | Como `admin` (no `super_admin`), `/admin/staff` → rol `admin` | 403 "Solo el Super Admin puede crear cuentas Admin" |
| ROLES-06 ✅ | Super Admin crea Admin | Repetir ROLES-05 como `super_admin` | Se crea correctamente |
| ROLES-07 ❌ | Nadie crea otro Super Admin desde la app | Cualquier rol, intentar crear `role=super_admin` vía API directa | 403/400 — no hay opción en la UI, y el endpoint también lo rechaza |
| ROLES-08 ❌ | Super Admin se autodesactiva | Como `super_admin`, en `/admin/staff` intentar desactivar su propia fila | Botón oculto en la UI; si se llama al endpoint directo, 403 "Un Super Admin no se puede desactivar" |
| ROLES-09 ❌ | Cualquiera se autodesactiva | Como `admin`, intentar desactivar su propia cuenta | 400 "No puedes desactivar tu propia cuenta" |
| ROLES-10 ❌ | Admin desactiva a otro Admin | Como `admin` (no super), intentar desactivar otra cuenta `admin` | 403 "No autorizado" |
| ROLES-11 ✅ | Reactivar cuenta | Como `admin`+, reactivar una cuenta desactivada (no super_admin) | Vuelve a poder loguearse |
| ROLES-12 ✅ | Borrado permanente respeta jerarquía | `coordinador` borra un `digitador` | Se borra, `EventStaffAuthorization` asociadas también, `Event`/`AccessLog` quedan con la referencia en NULL, no se borran |
| ROLES-13 ❌ | Coordinador borra a un Admin | `coordinador` intenta `DELETE /api/staff/{admin_id}` | 403 "Un coordinador no puede borrar cuentas de rol 'admin'" |
| ROLES-14 ❌ | Cualquiera se borra a sí mismo | Cualquier rol, intentar borrarse | 400 "No puedes borrar tu propia cuenta" |
| ROLES-15 ❌ | `digitador` intenta acceder a `/admin/staff` | Loguearse como `digitador`, ir a `/admin/staff` | Redirige a `/` |
| ROLES-16 ❌ | `cliente` intenta registrar/reconocer | Loguearse como `cliente`, intentar `POST /api/recognize` o `/api/register` directo (curl/Postman) | 403 (la jerarquía de `require_role("digitador")` excluye a `cliente`) |
| ROLES-17 ✅ | `cliente` sí ve el directorio | Como `cliente`, entrar al evento → pestaña Directorio en Vivo | Ve la tabla con datos, sin poder escanear/registrar |

---

## 3. Clientes (Tenants)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| TENANT-01 ✅ | Crear cliente | `coordinador`+, `/` → "Nuevo cliente", `name="Prueba SAS"` | Se crea con un `id` (slug) y `client_code` aleatorio único, visible en el dashboard |
| TENANT-02 ✅ | Slug duplicado se resuelve solo | Crear dos clientes con el mismo `name` | El segundo obtiene un `id` con sufijo (`prueba_sas_2`), sin error |
| TENANT-03 ✅ | Editar cliente | Cambiar `contact_email` de un cliente existente | Se refleja el cambio |
| TENANT-04 ❌ | Borrar cliente con eventos asociados | Intentar borrar un cliente que ya tiene al menos un evento | 400 "el cliente tiene eventos asociados" |
| TENANT-05 ✅ | Borrar cliente sin eventos | Crear un cliente nuevo (sin eventos) y borrarlo | Se elimina sin error |
| TENANT-06 ❌ | `digitador` intenta crear/listar clientes | Como `digitador`, `GET/POST /api/tenants` | 403 |

---

## 4. Eventos — CRUD y ciclo de vida

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| EVENT-01 ✅ | Crear evento completo | Llenar todos los campos obligatorios (código, nombre, fechas, horarios, país/ciudad, coordinador) | Se crea con `status="creado"` |
| EVENT-02 ❌ | Falta un campo obligatorio | Omitir `location` o cualquier campo no-`notes` | 422 (Pydantic) o el formulario no deja enviar |
| EVENT-03 ❌ | `event_code` duplicado | Crear un evento con un código que ya existe (de cualquier cliente) | 400 "Ya existe un evento con el código..." — antes de tocar la base |
| EVENT-04 ❌ | `coordinator_staff_id` inválido | Mandar un `id` que no sea un `StaffUser` con rol `coordinador` | 400 "El coordinador asignado no es válido" |
| EVENT-05 ❌ | Fecha de inicio posterior a la de fin | `start_date > end_date` | 400 "La fecha de inicio no puede ser después de la fecha de fin" |
| EVENT-06 ❌ | Fecha de montaje posterior al inicio | `setup_date > start_date` | 400 "La fecha de montaje debe ser el día del inicio o antes" |
| EVENT-07 ✅ | Cliente (tenant) inexistente rechazado | `tenant_id` que no existe | 404 "Cliente (tenant) no encontrado" |
| EVENT-08 ✅ | Cambiar estado libremente | Con el evento en `creado`, cambiar el `<select>` de estado a `en_proceso`, luego a `finalizado`, luego de vuelta a `creado` | Cada cambio pide `showConfirm`; si se confirma, se aplica; si se cancela, el `<select>` vuelve a su valor anterior |
| EVENT-09 ❌ | Estado inválido por API directa | `PATCH /api/events/{id}` con `status="activo"` (valor viejo, ya no existe) | 400 "Estado inválido" |
| EVENT-10 ❌ | Cambiar `event_code` a uno ya usado por otro evento | `PATCH` con un código existente de OTRO evento | 400 "Ya existe un evento con el código..." |
| EVENT-11 ✅ | Búsqueda de eventos | `/` (coordinador+), buscar por parte del nombre/código/ciudad | Filtra por prefijo de palabra (ver `_matches_by_word_prefix`) — "cor" encuentra "Corferias", "ferias" NO |
| EVENT-11b ✅ | Búsqueda sin tildes (Sprint 2 Fix 1) | Cliente/evento con tilde en el nombre (ej. "Café Central"), buscar `cafe` (sin tilde) | Encuentra el resultado igual — insensible a tildes/ñ, no solo a mayúsculas |
| EVENT-12 ✅ | Borrar evento con historial | Borrar un evento que ya tiene `AccessLog`/`EventStaffAuthorization` | Se borra sin `ForeignKeyViolation`; los `AccessLog` quedan con `event_id=NULL` (no se borran), las `EventStaffAuthorization` de ese evento sí se borran |
| EVENT-13 ❌ | `digitador`/`cliente` sin autorización explícita | Crear un evento nuevo y, SIN autorizar a un `digitador` existente, hacer que ese `digitador` intente `/kiosk/{event_id}` | 403/redirige a `/` |
| EVENT-14 ❌ | `digitador` entra a evento no `en_proceso` | Autorizar a un `digitador` para un evento en estado `creado` o `finalizado`, intentar `/kiosk/{event_id}` | Bloqueado (redirige) — `get_event_for_staff` solo deja pasar `en_proceso` para `digitador`/`cliente` |
| EVENT-15 ✅ | `coordinador`+ entra sin importar el estado | Como `coordinador`, entrar a un evento `creado` o `finalizado` | Entra sin problema (puede ver Directorio/gestionar Usuarios del Evento aunque no esté `en_proceso`) |

---

## 5. Selección — `/kiosk/{event_id}` (`kiosk_select.html`)

**Cambio 2026-09-21:** Facial y Cédula se unificaron en una sola vista de Registro (`/kiosk/{event_id}/registro`) — ya no son dos tarjetas separadas. Ver sección 6.

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| SELECT-01 ✅ | `cliente` va directo a su vista | Loguear como `cliente` con un evento `en_proceso` autorizado, entrar | Va derecho a `kiosk_registro.html` en su variante reducida (Estadísticas + Directorio de solo lectura), sin ver la pantalla de selección |
| SELECT-02 ✅ | Otros roles ven las tarjetas | Loguear como `digitador`/`coordinador`/`admin`, entrar a un evento | Ve `kiosk_select.html`: **Registro** (una sola tarjeta), QR (deshabilitada), Adjuntar Base de Datos |
| SELECT-03 ❌ | `digitador` no ve "Adjuntar Base de Datos" | Loguear como `digitador`, ir a `/kiosk/{event_id}` | La tarjeta "Adjuntar Base de Datos" NO aparece; forzando la URL `/kiosk/{id}/roster` directo también redirige (fix 2026-09-21, `_resolve_kiosk_page(min_role="coordinador")`) |
| SELECT-04 ✅ | Pill de estado visible | Evento en cualquier estado | La pill muestra "Creado"/"En Proceso"/"Finalizado" correctamente |
| SELECT-05 ✅ | Aviso cuando no está en proceso | Evento en `creado` o `finalizado` | Aparece el aviso amarillo "el escáner y el registro no van a funcionar..." |
| SELECT-06 ✅ | El ícono/subtítulo de "Registro" refleja `facial_enabled` | Comparar la tarjeta en un evento con `facial_enabled=True` vs uno con `False` | Ícono y texto distinto (📸 "Escáner facial, cédula y directorio" vs 🪪 "Cédula (lector o manual) y directorio") |
| SELECT-07 ❌ | Rutas viejas redirigen | Ir directo a `/kiosk/{event_id}/facial` o `/kiosk/{event_id}/cedula` (enlaces guardados de antes de la unificación) | 302 a `/kiosk/{event_id}/registro`, no 404 |

---

## 6. Registro unificado (`/kiosk/{event_id}/registro`, `kiosk_registro.html`)

**Reemplaza las viejas secciones "Facial" y "Cédula"** (unificadas 2026-09-21 — ver `CLAUDE.md`). El contenido de esta pantalla depende de `Event.facial_enabled`: se enciende solo (nunca se apaga solo) la primera vez que se sube un roster con zip de fotos para ese evento (ver ROSTER-28/29/30 en la sección 7.5). Requiere evento en `en_proceso` para las acciones de escaneo/registro (no para navegar a la página).

### 6.1 Con `facial_enabled = True` (evento con fotos cargadas)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| REG-01 ✅ | Aparece la pestaña de escáner | Entrar a Registro en un evento con `facial_enabled=True` | Pestaña activa por defecto es "Escáner de Acceso"; existe además "Registro Individual" (con campo de foto), "Exportar Reporte", "Directorio en Vivo", "Usuarios del Evento" |
| REG-02 ✅ | Registro manual con foto | Pestaña "Registro Individual", llenar datos + subir foto con un rostro claro | `POST /api/register` responde éxito, aparece en el Directorio como "Nuevo" |
| REG-03 ❌ | Foto sin rostro detectable | Subir una imagen sin cara (ej. un paisaje) | `{"error": "No se detectó un rostro en la fotografía."}`, no crea el registro |
| REG-04 ❌ | Botón de escanear deshabilitado si no está en proceso | Evento en `creado`/`finalizado`, ir a la pestaña Escáner | Botón "Escanear Rostro" deshabilitado de verdad (no solo visualmente) |
| REG-05 ❌ | Forzar `/api/recognize` con evento no en proceso | Vía API directa (curl), evento `creado` | 403 "todavía no ha comenzado" (`require_event_in_progress`) |
| REG-06 ✅ | Reconocimiento de rostro ya registrado | Con una persona ya registrada (con foto), escanear su rostro de nuevo | `result: "SÍ"`, se abre el formulario para confirmar/editar y "Guardar y Autorizar Acceso" |
| REG-07 ❌ | Rostro no coincide con nadie | Escanear un rostro que no está en la base | `result: "NO", details: "Denegado"` |
| REG-08 ✅ | Editar datos al reconocer | Tras un reconocimiento exitoso, cambiar algún campo y "Guardar" | Pide confirmación ("¿seguro que quieres sobrescribir sus datos?"), al aceptar actualiza, crea `AccessLog record_type="Actualizado"` y refresca el Directorio |
| REG-09 ❌ | Alta manual sin adjuntar foto (aunque el evento sí tenga `facial_enabled`) | El campo de foto es `required` en el HTML — verificar que también esté protegido si se salta esa validación (API directa sin `file`) | Con `facial_enabled=True` el campo es obligatorio en la UI; por API directa sin `file`, ver REG-16 (el backend trata `file` ausente/vacío igual en los dos modos) |

### 6.2 Con `facial_enabled = False` (evento sin fotos, "cédula tradicional")

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| REG-10 ✅ | No aparece la pestaña de escáner | Entrar a Registro en un evento con `facial_enabled=False` | Sin pestaña "Escáner de Acceso"; pestaña activa por defecto es "Directorio en Vivo"; "Registro Individual" NO pide fotografía |
| REG-11 ✅ | Registro manual sin foto | Pestaña "Registro Individual", llenar datos (sin campo de foto visible) y guardar | Se crea el `User` sin `face_encoding`, aparece en el Directorio |

### 6.3 Directorio en Vivo con búsqueda (aplica en AMBOS modos — 6.1 y 6.2)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| REG-12 ✅ | Búsqueda en vivo por cédula | Escribir parte de una cédula en el campo correspondiente | La tabla filtra en vivo, sin llamar al backend en cada tecla |
| REG-13 ✅ | Búsqueda en vivo por nombre | Escribir parte de un nombre/apellido | Filtra correctamente (combina nombre+apellido) |
| REG-14 ✅ | Búsqueda en vivo por empresa | Escribir parte de una empresa | Filtra correctamente |
| REG-15 ✅ | Combinar los 3 filtros | Llenar cédula + nombre + empresa a la vez | Solo muestra filas que cumplen los TRES simultáneamente |
| REG-16 ✅ | Acreditar desde la tabla | Sobre una fila "No registrado", clic en "Acreditar" | Cambia a "Registrado", desaparece el botón, llama `POST /api/checkin-cedula` |
| REG-17 ✅ | Atajo de lector de código de barras | Escribir una cédula EXACTA existente en el campo de búsqueda y presionar Enter | Acredita al instante sin pasar por la tabla |
| REG-18 ❌ | Cédula no encontrada | Escribir una cédula que no existe y Enter | Salta automáticamente a la pestaña "Registro Individual" con esa cédula precargada en el campo ID (ya NO aparece un mini-formulario aparte dentro del Directorio, como antes) |
| REG-19 ✅ | Completar el alta tras REG-18 | Llenar nombre/apellido en "Registro Individual" (con la cédula ya precargada) y guardar | Se crea el `User` y queda acreditado; si `facial_enabled=True` puede requerir foto, si es `False` no |
| REG-20 ✅ | Editar/Guardar/Eliminar (patrón compartido) | Sobre cualquier fila, "Editar" → cambiar un campo → "Guardar"; luego "Eliminar" | Edita perfil vía PATCH; "Eliminar" pide confirmación y borra solo el log de asistencia (no el `User`) — ver también DIR-06 (visibilidad de estos botones según rol) |
| REG-21 ❌ | Evento no en proceso | Evento `creado`/`finalizado`, campo de cédula del Directorio | Input deshabilitado, aviso amarillo visible |
| REG-22 ✅ | Exportar reporte (no visible para `digitador`) | Pestaña "Exportar Reporte" → botón | Descarga un `.xlsx` con las columnas del formato legacy |
| REG-23 ❌ | `digitador` no ve "Exportar Reporte" | Loguear como `digitador` | La pestaña no aparece |
| REG-24 ✅ | `cliente` ve Directorio de solo lectura | Loguear como `cliente` | Ve el Directorio con búsqueda, pero SIN botón "Acreditar" y SIN el atajo de Enter (`canAccredit = STAFF_ROLE !== "cliente"`) |

### 6.4 Campos opcionales en "Registro Individual" (2026-09-22)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| REG-25 ✅ | Campo "Tipo de Asistente" presente | Abrir "Registro Individual" | Existe el campo (antes faltaba en el alta manual aunque sí estaba en el roster) |
| REG-26 ✅ | Campos opcionales ya rotulados aparecen solos | Evento que YA tiene `optional_field_labels` (ej. de una carga de Excel previa) | Cada `opcional_N` rotulado aparece como input con su nombre real (no "Opcional N") |
| REG-27 ✅ | Agregar un campo opcional nuevo | Clic en "+ Agregar campo opcional" | Pide el nombre (modal `promptOptionalLabels`), al confirmar aparece el input nuevo en el formulario |
| REG-28 ❌ | Cancelar al agregar | Clic en "+ Agregar campo opcional", cancelar el modal | No se agrega ningún campo |
| REG-29 ✅ | Guardar con un campo opcional agregado | Completar REG-27, llenar el nuevo campo, guardar el registro | Se crea el `User` con ese valor en `extra_fields`; `Event.optional_field_labels` queda con el nombre elegido — visible en la siguiente carga de la página sin volver a preguntarlo |
| REG-30 ✅ | Reusar un campo agregado para la siguiente persona | Tras REG-29, sin recargar la página, registrar a alguien más | El campo agregado sigue en el formulario (no desaparece), se puede llenar de nuevo sin preguntar el nombre otra vez |
| REG-31 ❌ | Agotar los 30 campos opcionales | Agregar 30 campos opcionales en el mismo formulario/evento | Al intentar un 31º, toast de error "Ya se usaron los 30 campos opcionales disponibles" — no se agrega |
| REG-32 ✅ | Evento sin ningún Excel cargado | Evento nuevo, sin roster nunca subido, `optional_field_labels={}` | El formulario arranca sin campos opcionales, pero "+ Agregar campo opcional" funciona igual — mismo mecanismo que un evento con Excel |

---

## 7. Adjuntar Base de Datos (`/kiosk/{event_id}/roster`, `POST /api/bulk_register`)

### 7.1 Formato de archivo

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-01 ✅ | Descargar plantilla | Clic en "Descarga la plantilla de Excel" | Descarga `plantilla_carga_base_asistentes.xlsx` con las columnas correctas |
| ROSTER-02 ✅ | Subir `.xlsx` válido | Llenar la plantilla con 2-3 personas reales, subir sin zip | `count` = número de filas, sin `errors` graves, aparecen en el Directorio del evento |
| ROSTER-03 ✅ | Subir `.csv` válido | Mismo contenido pero guardado como `.csv` (`,` o `;` como separador) | Mismo resultado que ROSTER-02 — el formato de origen no debería importar |
| ROSTER-04 ❌ | Archivo con extensión no soportada | Subir un `.txt` o `.docx` | El `<input accept=".xlsx,.csv">` debería filtrarlo en el navegador; si se fuerza por API, se procesa como CSV y probablemente reporta filas vacías/erróneas — no debe tumbar el servidor (500) |
| ROSTER-05 ❌ | Evento finalizado | Marcar el evento como `finalizado`, intentar subir la base | 400 "No se puede cargar la base de un evento finalizado" |
| ROSTER-06 ✅ | Cargar sobre evento `creado` (antes de `en_proceso`) | Evento recién creado, subir el roster | Funciona (es preparación previa, `require_event_in_progress` NO aplica a `bulk_register`) |

### 7.2 Reconocimiento facial opcional

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-07 ✅ | Checkbox sin marcar | Subir roster SIN marcar "¿Desea activar el reconocimiento facial?" | Se ignora cualquier campo de zip; personas quedan cargadas (identidad + `EventAttendee`) pero SIN `face_encoding` |
| ROSTER-08 ✅ | Checkbox marcado + zip válido | Marcar el checkbox, subir un `.zip` con fotos nombradas `<cédula>.jpg` | Aparece el campo de zip; tras subir, esas personas quedan con `face_encoding` y se pueden reconocer por cara |
| ROSTER-09 ❌ | Checkbox marcado sin subir zip | Marcar el checkbox pero dejar el campo de zip vacío | El frontend quita el campo `zip_file` del envío (`formData.delete`); se procesa igual que ROSTER-07, sin error |
| ROSTER-10 ❌ | Foto en el zip sin nombre de cédula coincidente | Zip con una foto `random.jpg` que no corresponde a ninguna cédula del roster | Se guarda el archivo en `known_people/` pero no se asocia a nadie (no hay cédula `random` en la base) — no debería romper la carga del resto |

### 7.3 Campos opcionales dinámicos (`opcional_1`..`opcional_30`)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-11 ✅ | Primera carga con opcionales nuevos | Subir un archivo con `opcional_1` y `opcional_3` llenos (con datos) para un evento que nunca los ha usado | Responde `{"result": "NEEDS_LABELS", "fields": ["opcional_1", "opcional_3"]}`, **nada se guarda todavía** |
| ROSTER-12 ✅ | Completar las etiquetas | Tras ROSTER-11, el modal pide un nombre para cada campo; llenar ambos y "Guardar y continuar" | Se reenvía la MISMA carga con `field_labels`, esta vez sí procesa las filas y guarda `Event.optional_field_labels` |
| ROSTER-13 ✅ | Segunda carga, mismas columnas | Subir OTRO archivo al MISMO evento con las mismas columnas `opcional_1`/`opcional_3` | Ya NO pregunta las etiquetas (ya estaban guardadas para ese evento) — procesa directo |
| ROSTER-14 ✅ | Columnas opcionales vacías se ignoran | Subir un archivo con `opcional_5` en el encabezado pero SIN ningún valor en ninguna fila | No se pregunta por `opcional_5` (no se considera "usado") |
| ROSTER-15 ✅ | Mismo número de opcional, otro evento | Repetir ROSTER-11/12 en un evento DISTINTO usando `opcional_1` con un significado distinto | Cada evento pregunta y guarda su propia etiqueta — no se mezclan entre eventos |
| ROSTER-16 ✅ | Encabezado con variantes de formato | Probar encabezados `"Opcional 1"`, `"opcional_1"`, `"OPCIONAL1"` en distintos archivos | Los tres se reconocen como el mismo campo `opcional_1` |
| ROSTER-17 ❌ | Número fuera de rango | Encabezado `"opcional_31"` o `"opcional_0"` | Se ignora por completo (no es un campo reconocido, `MAX_OPTIONAL_FIELDS=30`) |
| ROSTER-18 ✅ | Columna "tipo de asistente" | Llenar esa columna (no es parte de los 30 opcionales, es fija) | Se guarda en `User.opt_1`, visible en el Directorio como "Tipo Asistente" |

### 7.4 Validación con referencia de celda

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-19 ❌ | Cédula/ID vacío en una fila | Dejar la celda de `id` vacía en una fila con nombre/apellido | `❌ Fila N (AN): sin ID/cédula, se omitió esta fila.` — esa fila NO se guarda, el resto sí |
| ROSTER-20 ❌ | Nombre vacío | Dejar `nombres` vacío en una fila con cédula válida | `⚠️ Fila N (BN): falta el nombre.` — la fila SÍ se guarda (con nombre vacío), solo avisa |
| ROSTER-21 ❌ | Apellido vacío | Igual que ROSTER-20 pero con `apellidos` | `⚠️ Fila N (CN): falta el apellido.` — se guarda igual |
| ROSTER-22 ❌ | Correo mal formado | `correo = "juanexample.com"` (sin `@`) | `⚠️ Fila N (celda): el correo '...' no parece válido — se guardó igual, revísalo.` |
| ROSTER-23 ❌ | Teléfono con letras | `telefono = "abc123"` | `⚠️ Fila N (celda): el teléfono '...' tiene caracteres raros — se guardó igual, revísalo.` |
| ROSTER-24 ❌ | Cédula convertida a número por Excel | Escribir la cédula en una celda con formato "Número" en Excel (queda como `1020304050.0`) | `ℹ️ Fila N (AN): la cédula venía como '...0' — Excel la convirtió a número. Se corrigió automáticamente a '...'.` — se guarda con el valor YA corregido |
| ROSTER-25 ❌ | Cédula repetida en el mismo archivo | Dos (o más) filas con la misma cédula | `⚠️ La cédula 'X' aparece repetida en N filas (A2, A5, ...) — se combinaron los datos y quedó lo de la última fila.` — **no debe tumbar la carga (500)**, solo un `User` resultante con los datos de la última fila procesada |
| ROSTER-26 ✅ | Carga con varios problemas a la vez | Combinar en un solo archivo: una fila sin ID, una con nombre vacío, una con correo malo, y una cédula repetida | Todos los mensajes aparecen juntos en `errors[]`, cada uno con su celda; la carga termina con `count` = filas válidas procesadas, sin 500 |
| ROSTER-27 ✅ | Visualización por severidad | Repetir ROSTER-26 desde el navegador | En pantalla aparecen 3 cajas de color separadas: roja (❌ filas omitidas), amarilla (⚠️ revisar dato), azul (ℹ️ correcciones automáticas) |

### 7.5 `Event.facial_enabled` (2026-09-21 — controla la vista de Registro unificada, ver sección 6)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-28 ✅ | Primera carga con zip enciende `facial_enabled` | Evento nuevo (`facial_enabled=False` por default) → subir roster marcando el checkbox + zip de fotos | `event.facial_enabled` pasa a `True`; entrar a `/kiosk/{event_id}/registro` ya muestra la pestaña de escáner (ver REG-01) |
| ROSTER-29 ✅ | Subida posterior SIN zip no lo apaga | En el MISMO evento de ROSTER-28 (ya con `facial_enabled=True`), subir otro roster sin marcar el checkbox | `facial_enabled` sigue en `True` — no se apaga solo |
| ROSTER-30 ✅ | Evento sin ninguna carga con fotos | Evento nuevo, subir solo roster sin zip (o no subir nada todavía) | `facial_enabled=False`, Registro se comporta como cédula tradicional (ver REG-10/11) |

### 7.6 Bloqueo de re-carga con el evento EN PROCESO (2026-09-22)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| ROSTER-31 ✅ | Aviso al cargar con el evento en proceso (primera vez) | Evento `en_proceso`, `roster_uploaded=False` (nunca se le cargó nada), subir un roster | Aparece `showConfirm` amarillo preguntando si está seguro; al confirmar, la carga procede normal y `roster_uploaded` pasa a `True` |
| ROSTER-32 ❌ | Cancelar el aviso | Repetir ROSTER-31 pero cancelar el modal | No se manda la petición al backend, no pasa nada |
| ROSTER-33 ❌ | Re-carga bloqueada | En el MISMO evento de ROSTER-31 (ya `en_proceso` + `roster_uploaded=True`), intentar subir OTRO roster | Tras confirmar el aviso, el backend responde 400: "Este evento ya tiene una base cargada y está EN PROCESO... crea un evento nuevo" — no se procesa ninguna fila |
| ROSTER-34 ✅ | Re-carga permitida si el evento NO está en proceso | Evento en `creado` con `roster_uploaded=True` (se le cargó algo antes de arrancar), subir otro roster | Se permite sin bloqueo ni aviso especial — es preparación normal antes de que empiece |
| ROSTER-35 ✅ | Evento que arranca sin base nunca se ve afectado | Evento `en_proceso` que jamás tuvo un roster (`roster_uploaded=False`), todo el registro fue manual | No hay ningún bloqueo — el aviso de ROSTER-31 es solo una confirmación, no impide seguir operando 100% manual |

---

## 8. Advertencia de doble registro (`force`)

Aplica a `POST /api/recognize`, `POST /api/checkin-cedula` y `POST /api/register` (alta manual de alguien ya existente).

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| DUP-01 ❌ | Reconocer dos veces a la misma persona (Facial) | Escanear un rostro ya acreditado en este evento, escanear el MISMO rostro otra vez | Segunda vez: aparece el modal amarillo pastel "¿Seguro que deseas registrarla de nuevo?" — NO crea un segundo log automáticamente |
| DUP-02 ✅ | Confirmar el doble registro | En DUP-01, aceptar el modal | Reintenta la petición con `force=true`, esta vez sí crea el log |
| DUP-03 ✅ | Cancelar el doble registro | En DUP-01, cancelar el modal | No pasa nada, no se crea ningún log nuevo |
| DUP-04 ❌ | Acreditar dos veces por Cédula | Acreditar una cédula, luego intentar acreditarla de nuevo (botón "Acreditar" en la tabla, o el atajo de Enter) | Mismo modal de advertencia; confirmar/cancelar igual que DUP-02/03 |
| DUP-05 ❌ | Alta manual de alguien que ya tiene log en este evento | Desde "Registro Individual" (Facial) o el alta manual de Cédula, intentar re-registrar manualmente a alguien que ya se acreditó hoy en este evento | Mismo flujo `DUPLICADO`/`force` |
| DUP-06 ✅ | Reutilizar a alguien de OTRO evento (no debe avisar) | Una persona que asistió a un evento pasado (mismo tenant), sin log en el evento ACTUAL, se registra/reconoce/acredita en el evento actual por primera vez | NO debe salir advertencia — se asocia directo (es la primera vez en ESTE evento) |
| DUP-07 ✅ | El modal muestra el nombre correcto | Repetir DUP-01 con una persona con nombre conocido | El mensaje del modal incluye el nombre real de la persona (viene en `data` de la respuesta `DUPLICADO`) |

---

## 9. Directorio en Vivo (`static/js/directory.js`, usado desde la vista de Registro unificada)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| DIR-01 ✅ | Ver el directorio del evento | Entrar a la pestaña/pantalla de Directorio | Muestra únicamente personas asociadas a ESTE evento (roster precargado ∪ quien se presentó), no todo el tenant |
| DIR-02 ✅ | Editar un registro | "Editar" → cambiar campos → "Guardar" | `PATCH /api/users/{id}` actualiza, toast de éxito |
| DIR-03 ❌ | Guardar con campo vacío obligatorio | Borrar el nombre por completo en modo edición y "Guardar" | (Verificar: hoy no hay validación de "no vacío" en el PATCH — si se guarda vacío sin avisar, es una mejora pendiente, no necesariamente un bug bloqueante) |
| DIR-04 ✅ | Eliminar registro de asistencia | "Eliminar" en una fila | Pide confirmación explicando que NO borra al `User`, solo su log de hoy; al confirmar, la fila vuelve a "No registrado" |
| DIR-05 ✅ | Directorio NO mezcla eventos distintos | Comparar el Directorio de dos eventos distintos del mismo cliente, con personas distintas en cada uno | Cada evento muestra solo lo suyo |
| DIR-06 ❌ | `digitador`/`cliente` intentan Editar/Eliminar | Como `digitador`, ver la tabla del Directorio | **Arreglado 2026-09-21:** la celda de acción viene vacía desde el principio para `digitador`/`cliente` (sin botón "Editar" siquiera) — `directory.js` compara `window.STAFF_ROLE` contra `EDIT_ROLES`/`DELETE_ROLES` antes de crear los botones, mismos mínimos que exige el backend (`PATCH` = `coordinador`+, `DELETE .../logs` = `admin`+). Verificar además por API directa que ambos siguen dando 403 para roles insuficientes (defensa en profundidad, no solo ocultar en la UI) |
| DIR-07 ✅ | `coordinador` ve Editar pero no Eliminar | Como `coordinador` (no admin), ver una fila y entrar en modo edición | Aparece "Editar"/"Guardar", pero "Eliminar" nunca se revela (requiere `admin`+) |
| DIR-08 ✅ | Búsqueda por nombre/empresa sin tildes (Sprint 2 Fix 1) | Persona cargada como "María José Ñúñez Gómez", buscar `maria jose` (sin tildes, minúsculas) | La encuentra igual — antes daba "Sin resultados" |
| DIR-09 ✅ | Prefijo por palabra, no substring (Sprint 2 Fix 1) | Con "María" y "Amaya" cargadas en el mismo evento, buscar `Ma` en el campo de nombre | Solo aparece "María" (su nombre EMPIEZA con "Ma"); "Amaya" NO aparece aunque contenga "ma" en medio |
| DIR-10 ✅ | Cédula sigue siendo substring (sin cambiar) | Buscar por los ÚLTIMOS dígitos de una cédula (no el inicio) | Sigue encontrándola — el campo de cédula no cambió a prefijo, solo nombre/empresa |
| DIR-11 ✅ | Contador "N sin registrar" (Sprint 2 Fix 2) | Evento con roster precargado, algunas personas sin presentarse todavía | Aparece un botón/badge "⚠️ N sin registrar" arriba de la tabla, con el conteo correcto de filas en estado "No registrado" |
| DIR-12 ✅ | Clic en el contador filtra la tabla | Clic en el botón de DIR-11 | Solo quedan visibles las filas "No registrado"; el botón queda visualmente "activo" |
| DIR-13 ✅ | El filtro de "sin registrar" se combina con la búsqueda | Con el filtro de DIR-12 activo, escribir algo en el campo de nombre | Se aplican AMBOS filtros a la vez (no se reemplazan) |
| DIR-14 ✅ | El contador se oculta si no hace falta | Evento donde TODOS ya se registraron (0 "No registrado") y el filtro no está activo | El botón/badge no aparece |

---

## 10. Reporte Excel (`GET /api/report`)

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| REP-01 ✅ | Descargar reporte | Como `coordinador`+, "Exportar Reporte" | Descarga `.xlsx` con una fila por `User` del tenant, columnas del formato legacy |
| REP-02 ❌ | `digitador` intenta descargar | Llamar `GET /api/report` directo como `digitador` | 403 (`require_role("coordinador")`) |

---

## 11. Seguridad / límites de acceso (regresión)

Estos casos verifican que las correcciones de seguridad ya aplicadas siguen vigentes — repetir tras cualquier cambio en `auth.py`, `main.py` o los routers.

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| SEC-01 ❌ | `/static/.env` | `curl http://localhost:5000/static/.env` | 404 (el archivo no debe existir en `static/`, y el repo no debe tenerlo commiteado) |
| SEC-02 ❌ | Acceder a evento de OTRO tenant sin permiso | Como `digitador` autorizado solo al Evento A, intentar `/kiosk/{event_id_de_B}` | 403/redirige |
| SEC-03 ❌ | Modificar `event_id` en el body para operar sobre un evento ajeno | Como `digitador` autorizado a un evento, mandar `event_id` de otro evento en `/api/recognize` | 403 (se valida `get_event_for_staff` con el `event_id` real recibido, no confía en la sesión) |
| SEC-04 ✅ | Cookie de sesión con atributos correctos | Inspeccionar la cookie tras login | `HttpOnly`, `SameSite=Lax`; `Secure` solo si `ENVIRONMENT=production` |
| SEC-05 ❌ | SQL/NoSQL injection en búsqueda | `GET /api/events/search?q='; DROP TABLE events;--` | Sin efecto (usa ORM parametrizado, no SQL crudo) — devuelve simplemente 0 resultados |
| SEC-06 ❌ | XSS en campos de texto libre | Registrar una persona con `first_name = "<script>alert(1)</script>"` | El Directorio debe mostrarlo como texto plano (via `.innerText`, no `.innerHTML`), sin ejecutar el script — revisar `directory.js` sigue usando `td.innerText` |

---

## Resumen de cobertura

| Área | # de casos |
|---|---|
| Autenticación | 8 |
| Roles y permisos | 17 |
| Clientes (Tenants) | 6 |
| Eventos (CRUD + ciclo de vida) | 16 |
| Selección (`/kiosk/{event_id}`) | 7 |
| Registro unificado (con/sin cámara + Directorio compartido + opcionales en alta manual) | 32 |
| Roster (formato, facial opcional, opcionales dinámicos, validación, `facial_enabled`, bloqueo de re-carga) | 35 |
| Doble registro | 7 |
| Directorio en Vivo | 14 |
| Reporte | 2 |
| Seguridad | 6 |
| **Total** | **150** |

Actualiza este archivo cada vez que se agregue o cambie una funcionalidad — es un checklist vivo, no una foto única.
