# Análisis de flujo y UX (a nivel de código) — 17 de octubre de 2026

Base: rama `producto/fase0-ux`, partiendo de `migra/fase1-2` = `3aa23de`. Lo que dice «hoy» describe el código **antes** de la Fase 0; lo marcado ✅ quedó corregido en esta rama.

---

## a) Dónde se decide si un evento usa biometría y de dónde salen las fotos

### Columnas (tabla `events`)
| Columna | Qué significa | Quién la escribe |
|---|---|---|
| `facial_enabled` | el evento usa rostro | (1) Parámetros → paso guiado (`PUT /api/events/{id}/biometric-setup`, `app/routers/consents.py`); (2) `PUT /api/events/{id}/facial-enabled` (`app/routers/parametros.py`, **sin ningún botón que lo llame**); (3) **la carga con zip lo encendía sola** (`app/routers/api.py`, bulk) — ✅ retirado |
| `biometrics_locked` | candado «no usa biometría» | solo el paso guiado |
| `client_photos_before` | origen de la foto: A (fotos del cliente) / B (selfie) | solo el paso guiado (Paso 2) |
| `aceptar_enabled`, `accept_link_email`, `face_door_enabled`, `badge_bio_photo_allowed`, `face_door_liveness` (sin uso) | opciones del paso guiado / super administrador | paso guiado o su interruptor |

### Plantillas y JS
| Lugar | Qué hacía | Estado |
|---|---|---|
| `templates/kiosk_parametros.html` Paso 0 | **dos casillas** que podían contradecirse: «usará reconocimiento facial» (`bsFacial`) y «🚫 NO usa biometría (bloquear)» (`bsLocked`) | ✅ una sola opción («Usa rostro» / «No usa rostro (bloqueado)») |
| `templates/kiosk_roster.html` | casilla **«¿Desea activar el reconocimiento facial?»** que **no leía el estado del evento**: al marcarla pedía zip + declaración (flujo A) aunque el evento fuera B; sin marcarla, borraba el zip del envío y la carga ignoraba la fecha si el evento no tenía rostro | ✅ retirada: aviso de solo lectura con el estado y enlace a Parámetros; zip + declaración solo si el evento es A |
| `templates/kiosk_select.html` (tarjeta del menú) | «marca la casilla de reconocimiento facial si quieres activar la cámara» | ✅ «El reconocimiento facial se elige en Parámetros» |
| `templates/kiosk_registro.html` | muestra el escáner si `event.facial_enabled` | sin cambio |

### Fuente de verdad real, por decisión
| Decisión | Fuente de verdad (código) | Hoy / tras Fase 0 |
|---|---|---|
| **Carga**: ¿se guarda la fecha de nacimiento? | `birth_used = facial_enabled or (zip y sin candado)` en `_bulk_register_impl` | ✅ solo `facial_enabled` (Parámetros) |
| **Carga**: ¿se aceptan fotos (zip)? | la casilla de la pantalla de carga + `photos_authorized`; el zip **encendía** `facial_enabled` | ✅ solo si `facial_enabled` **y** `client_photos_before` (origen A); si no, 400 con el motivo |
| **/aceptar** (enlace y QR) | `_event()` en `app/routers/aceptar.py`: `aceptar_enabled` y `facial_enabled` y no `biometrics_locked` y no finalizado; selfie = `not client_photos_before` | sin cambio |
| **Puerta** (autoservicio) | `_door_event()` en `app/routers/door.py`: `face_door_enabled` y `facial_enabled` y no candado; la matriz = aceptación vigente (`consent.accepted_user_ids`) + vector + `is_biometric_enabled` | sin cambio |
| **Envío de enlaces** | `acceptmail.blocked_reason`: evento propio, sin candado, `facial_enabled` y `aceptar_enabled` | sin cambio |
| **Inscripción por formulario → enlace** | `formsvc.feed_submission`: `aceptar_enabled` y `accept_link_email` y `facial_enabled` y sin candado | sin cambio |
| **Menores** | `users.birth_date` (`app/minors.py`) + `users.is_biometric_enabled`; la fecha solo se guarda con rostro | sin cambio (regla de minimización) |
| **Purga de rostros** | `app/privacy.py` (eventos finalizados) | sin cambio |

**Lo que pasó el 16 de octubre**, según el código: la carga solo guarda la fecha si `facial_enabled` está en verdadero **en la base** en el momento de cargar. Si el Paso 0 estaba marcado en pantalla pero no se pulsó «Guardar y revisar», o se marcó después de cargar, la fecha se ignoró. Con la Fase 0 el aviso aparece **arriba** de la pantalla de carga, antes de elegir el archivo, y dice el estado guardado.

---

## b) Otras incongruencias del mismo tipo
1. **`PUT /facial-enabled`**: una segunda forma de encender el rostro, sin botón en la interfaz. Riesgo bajo, pero es otra fuente de verdad. *Propuesta:* retirarla en Fase 1 (o que llame a la misma validación del paso guiado).
2. **Estado del evento** se cambia en **tres lugares** (lista de eventos, lista de clientes, ventana de edición) con confirmaciones distintas. ✅ Los tres piden ahora la misma confirmación al pasar a «Finalizado», con sus consecuencias.
3. **Dos «autoregistros»:** `events.auto_register` (el escáner del digitador acredita solo) y la puerta de autoservicio (`face_door_enabled`, que siempre acredita sola con coincidencia clara). Se configuran en sitios distintos (menú de Registro / Parámetros). *Propuesta:* agruparlos en la pestaña «Reconocimiento facial» (Fase 1).
4. **Dos formas de enviar el enlace personal:** la casilla del Paso 3 «enviar el enlace al inscribirse por formulario» (`accept_link_email`) y el cuadro de envío masivo. Nombres parecidos, reglas distintas (el del formulario no es «confiable»). *Propuesta:* una sola sección «Invitaciones» con las dos opciones explicadas.
5. **Fecha de nacimiento**: se configura como campo (etiqueta/posición) en Parámetros, se carga en la base, se edita en «Editar persona» y se pide en /aceptar si falta; solo se **guarda** con rostro. La regla es correcta pero hoy solo se ve al cargar. ✅ El aviso ahora sale antes de cargar.
6. **Foto en la escarapela**: el elemento «foto» del diseñador de escarapelas usa la foto biométrica; su interruptor está en Parámetros (super administrador). El diseñador no avisa que saldrá en blanco. *Propuesta:* aviso en el diseñador (Fase 1).
7. **«Permitir aceptar desde el celular»** (`aceptar_enabled`) condiciona el enlace personal, el envío masivo y el QR del cartel, pero está dentro del Paso 3 como «opción».
8. **Modo contingencia**: lo decide el servidor (`CONTINGENCY_ENABLED`) y el dispositivo (preparado o no); la interfaz no dice en qué estado está el equipo hasta que se pierde la red.

---

## c) Auditoría UX del panel (medida en las plantillas)

**Tamaño de letra.** De 441 declaraciones de `font-size` en plantillas, CSS y JS, **320 son menores de 14 px** (las más comunes: 12,5 px ×82, 12,8 px ×48, 13,6 px ×95; hay de 9,9 a 11,8 px). Los textos de ayuda de Parámetros usan `0.78rem` = **12,5 px**.

**Contraste (texto sobre blanco; WCAG 1.4.3 pide 4,5:1):**
| Color | Contraste | Usos | Veredicto |
|---|---|---|---|
| `#666` | 5,74:1 (5,27 sobre `#F4F5F9`) | 113 | pasa |
| `#777` | **4,48:1** | 20 | **no llega** (por poco) |
| `#888` | **3,54:1** | 15 | **no llega** |
| `#999` | **2,85:1** | 2 | **no llega** |
| `#aaa` | **2,32:1** | 9 | **no llega** (p. ej. ayuda de la fecha en «Editar persona») |
| `#bbb` | **1,92:1** | 3 | **no llega** |
| `#b26a00` (avisos naranja) | **4,24:1** | 3 | **no llega** |
| `#D4AF37` (dorado como texto) | **2,1:1** | 1 | **no llega** (como fondo de botón con texto oscuro sí sirve) |

**Objetivos táctiles (WCAG 2.5.8, mínimo 24 × 24 px):** en Parámetros había **16 casillas de 18 × 18 px** (✅ las del Paso 0 y la de «Reemplazar fechas» pasan a 20 px; el resto, Fase 1 con etiquetas clicables de 24 px o más).

**Controles sin etiqueta accesible** (aproximado: `<input>` sin `<label>` que lo envuelva, sin `for=` y sin `aria-label`):
- Parámetros: **18** (p. ej. `amTo` correo de prueba, `mailSubject`, `mailColor`, `mailImgFile`, `mailTo`, `newAreaName`, `newItemName`, `newItemQty`, `logoFile`, `newOptionalFieldName`).
- Registro: **13** (búsquedas `searchCedula/Nombre/Entidad`, `scanMrzInput`, `regScanCedulaInput`, `regBirth`, `manualIdField`…).
- Adjuntar Base de Datos: **2** (`rosterFileInput` y el zip). ✅ «Reemplazar las fechas…» tiene ahora `aria-labelledby` (antes se leía «true»).

**Jerga técnica visible** (✅ corregido en Parámetros y en la tarjeta del menú): «SMTP», «Twilio», «`.env.example`», «`data/outbox/`», «encoding», «(página /aceptar)», «/kiosk/<id>/rostro». Quedan en otras pantallas (Fase 1): rutas `/kiosk/...` en textos de ayuda de Registro y Estado del sistema.

**Acciones destructivas sin confirmación:** las búsquedas de `DELETE` sin `showConfirm` cerca dieron 3; ninguna es grave: borrar una firma vacía al guardar (`field-render.js`), cancelar la autorización de un giro de la ruleta, y un falso positivo (el editor de formularios sí confirma). La confirmación que faltaba era **finalizar un evento** (✅).

**Páginas con varios botones de guardar:** Parámetros tiene **5** («Guardar cambios», «Guardar categorías», «Guardar correo», «Guardar pre-cálculo», «Guardar y revisar») y varios interruptores que guardan solos; el editor de formularios, 4. La persona no sabe qué se guardó y qué no. → Fase 1 (un Guardar por pestaña).
