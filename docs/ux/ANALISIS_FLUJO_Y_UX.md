# Análisis de flujo y UX (a nivel de código) — 17 de octubre de 2026

**Base:** la revisión visual del 16 de octubre (`docs/ux/26_REVISION_VISUAL_2026-10-16.md`, hecha en staging sobre PRUEBA-ACEPT-03) contrastada con el código de la rama `producto/fase0-ux` (desde `migra/fase1-2` = `3aa23de`). Para cada hallazgo se dice **qué confirma el código**, qué no, y si quedó resuelto en la Fase 0 (✅) o va a la Fase 1.

---

## 1. Hallazgo principal: la biometría se decidía en tres lugares (confirmado en el código)

### Dónde se lee y se escribe (columnas de `events`)
| Columna | Qué significa | Quién la escribía | Fase 0 |
|---|---|---|---|
| `facial_enabled` | el evento usa rostro | (1) paso guiado (`PUT /api/events/{id}/biometric-setup`, `app/routers/consents.py`); (2) `PUT /api/events/{id}/facial-enabled` (`app/routers/parametros.py`), **sin ningún botón que lo llame**; (3) **la carga con zip lo encendía sola** (`_bulk_register_impl`, `app/routers/api.py`) | ✅ (3) retirado; (2) queda solo como API, va a Fase 1 |
| `biometrics_locked` | candado «no usa biometría» | paso guiado, con **otra casilla** que podía contradecir a la anterior | ✅ opción única |
| `client_photos_before` | origen A (fotos del cliente) / B (selfie) | paso guiado (Paso 2); **la carga ofrecía el zip sin mirarlo** | ✅ zip solo con A |

### Dónde se usa (fuente de verdad real por decisión)
| Decisión | Código | Antes | Después de la Fase 0 |
|---|---|---|---|
| ¿Se guarda la fecha de nacimiento al cargar? | `birth_used` en `_bulk_register_impl` | `facial_enabled` **o** «vino un zip sin candado» | ✅ solo `facial_enabled` (Parámetros) |
| ¿Se aceptan fotos (zip)? | `bulk_register` | la casilla de la carga + la declaración; el zip encendía el rostro | ✅ solo con `facial_enabled` **y** origen A; si no, el servidor lo rechaza con el motivo |
| /aceptar (enlace personal y QR) | `_event()` en `app/routers/aceptar.py` | `aceptar_enabled` y `facial_enabled` y sin candado y no finalizado; selfie si origen B | sin cambio |
| Puerta (autoservicio) | `_door_event()` en `app/routers/door.py` | `face_door_enabled` y `facial_enabled` y sin candado; matriz = aceptación vigente + vector + adulto | sin cambio |
| Envío de enlaces | `acceptmail.blocked_reason` | evento propio, sin candado, `facial_enabled` y `aceptar_enabled` | sin cambio |
| Inscripción por formulario → enlace | `formsvc.feed_submission` | `aceptar_enabled`, `accept_link_email`, `facial_enabled`, sin candado | sin cambio |
| Menores | `users.birth_date` + `users.is_biometric_enabled` (`app/minors.py`) | la fecha solo se guarda con rostro (minimización) | sin cambio (regla legal) |
| Escáner en Registro | `kiosk_registro.html` | muestra la cámara si `facial_enabled` | sin cambio |

### El caso del 16 de octubre, según el código
La carga solo guardaba la fecha si `facial_enabled` era verdadero **en la base** o si venía un zip. La casilla de la carga **no leía el estado del evento**: al desmarcarla (porque pedía un zip que no aplicaba al origen B) se borraba el zip del envío. Si en ese momento el Paso 0 no estaba **guardado** (por ejemplo, marcado sin pulsar «Guardar y revisar»), la carga respondió «no se usa en este evento» y la fecha se perdió. Con la Fase 0, la carga **no decide nada**: muestra arriba el estado guardado y, con rostro, guarda siempre la fecha.

---

## 2. Otros hallazgos de la revisión, contrastados con el código

| Pantalla | Hallazgo de la revisión | Qué dice el código | Estado |
|---|---|---|---|
| Lista de eventos | Cambiar a «Finalizado» sin confirmación | La lista **sí pedía** «¿Cambiar el estado…?» (genérico, sin consecuencias); la **ventana de edición** no pedía nada; la lista de clientes, genérico | ✅ los tres piden la misma confirmación, con lo que pasa al finalizar |
| Lista / /aceptar | Nombres internos («8», «Juan David») salen en /aceptar | `/aceptar` muestra `event.name` tal cual; no hay un «nombre público» aparte ni validación | Fase 1 (nombre público o validación) |
| Menú del evento | Parámetros de último; 10 tarjetas iguales; emoji | Confirmado (`kiosk_select.html`) | Fase 1 (orden por ciclo + «Primeros pasos» + SVG) |
| Menú del evento | Tarjeta de la carga: «marca la casilla…» | Confirmado | ✅ «Carga masiva desde Excel/CSV» |
| Parámetros | ~12 secciones, 5 botones de guardar | Confirmado: «Guardar y revisar», «Guardar pre-cálculo», «Guardar categorías», «Guardar cambios», «Guardar correo», más «Radicar» e interruptores que guardan solos | Fase 1 (pestañas, un Guardar por pestaña) |
| Parámetros | Acciones destructivas mezcladas | Están **confirmadas**: «Borrar fotos del evento» pide **escribir el nombre del evento**; «Revocar» y «Suprimir TODOS los datos» piden confirmación con el efecto. Lo que falta es **moverlas** a una sección de Privacidad y darles estilo destructivo | Fase 1 (mover + estilo; ya confirman) |
| Parámetros | Jerga técnica | Confirmado: «.env.example», «data/outbox/», «SMTP», «Twilio», «encoding», «(página /aceptar)», «/kiosk/<id>/rostro», «Paso 0» | ✅ quitada (solo textos) |
| Adjuntar Base de Datos | «Reemplazar las fechas…» se lee «true» | Confirmado (la casilla tenía `value="true"` y la etiqueta sin `for`) | ✅ `<label for>` + `aria-labelledby` |
| Registro | Título «Control de Acceso FACIAL INTELIGENTE» también en cédula | Confirmado: el título cambia a «por Cédula» si no hay rostro, pero no nombra la tarea | Fase 1 («Registro y acceso») |
| Registro | La franja de supervisión funciona | — | se mantiene |
| /aceptar | La mejor pantalla: referencia visual | Confirmado: Montserrat 16–18 px, tarjeta blanca, un botón principal | base de la Fase 1 |
| Panel | Fuente distinta a la página pública | Confirmado: el panel usa `--font-body: 'Agrandir'` (`static/css/style.css`); /aceptar usa Montserrat | Fase 1 (unificar) |

### Otras incongruencias que encontré en el código (mismo tipo)
1. **`PUT /facial-enabled`**: una segunda forma de encender el rostro, sin botón. Fase 1: retirarla o que pase por la misma validación del paso guiado.
2. **Dos «autoregistros»**: `events.auto_register` (el escáner del digitador acredita solo, se activa desde Registro) y la puerta de autoservicio (Parámetros). Fase 1: juntarlos en la pestaña de Reconocimiento facial.
3. **Dos formas de enviar el enlace personal**: «enviar el enlace al inscribirse por formulario» (no confiable) y el envío masivo (confiable), en sitios distintos. Fase 1: una sección «Invitaciones».
4. **Foto en la escarapela**: el diseñador de escarapelas ofrece el elemento «foto» sin avisar que sale en blanco mientras su interruptor (super administrador) está apagado.
5. **«Permitir aceptar desde el celular»** condiciona el enlace, el envío y el QR, pero aparece como «opción» del Paso 3.
6. **Contingencia**: la decide el servidor (`CONTINGENCY_ENABLED`) y el equipo (preparado o no); la pantalla no dice en qué estado está el equipo hasta que se pierde la red.

---

## 3. Medición (WCAG 2.2, Material 3, Apple HIG, Android)

**Tipografía.** De 441 tamaños de letra declarados en plantillas, CSS y JS, **320 son menores de 14 px** (los más usados: 12,5 px ×82, 12,8 px ×48, 13,6 px ×95; hay de 9,9 a 11,8 px). La ayuda de Parámetros mide **12,5 px**. La referencia (Material 3, *body-medium*): 16 px con interlineado de 24 px; ayuda de 14 px como mínimo.

**Contraste (WCAG 1.4.3: 4,5:1 texto normal).**
| Color | Sobre blanco | Sobre `#F4F5F9` | Usos | Veredicto |
|---|---|---|---|---|
| `#666` | 5,74:1 | 5,27:1 | 113 | pasa |
| `#777` | **4,48:1** | **4,11:1** | 20 | no llega |
| `#888` | **3,54:1** | **3,25:1** | 15 | no llega |
| `#999` | **2,85:1** | **2,62:1** | 2 | no llega |
| `#aaa` | **2,32:1** | **2,13:1** | 9 | no llega (p. ej. ayuda de la fecha en «Editar persona») |
| `#bbb` | **1,92:1** | **1,76:1** | 3 | no llega |
| `#b26a00` (avisos naranja) | **4,24:1** | **3,89:1** | 3 | no llega |
| `#D4AF37` (dorado como texto) | **2,1:1** | **1,93:1** | 1 | no llega (como fondo con texto oscuro sí sirve) |

**Tamaño táctil (WCAG 2.5.8: 24 × 24 px mínimo; 44 pt Apple, 48 dp Android).** Parámetros tenía **16 casillas de 18 × 18 px**. ✅ Las del Paso 0 y «Reemplazar fechas» pasan a 20 px con la etiqueta entera clicable; el resto en la Fase 1.

**Controles sin nombre accesible** (aproximado: sin `<label>` que los envuelva, sin `for=` y sin `aria-label`): Parámetros **18** (`amTo`, `mailSubject`, `mailColor`, `mailImgFile`, `mailTo`, `newAreaName`, `newItemName`, `newItemQty`, `logoFile`, `newOptionalFieldName`…), Registro **13** (`searchCedula`, `searchNombre`, `searchEntidad`, `scanMrzInput`, `regScanCedulaInput`, `regBirth`, `manualIdField`…), Adjuntar Base de Datos **2** (archivo y zip).

**Acciones destructivas.** Todas las de borrado llevan confirmación (la del evento entero pide escribir su nombre). Las búsquedas automáticas solo encontraron dos sin confirmación, ambas menores: borrar una firma vacía al guardar y cancelar la autorización de un giro de la ruleta. La confirmación que faltaba era **finalizar un evento** desde la ventana de edición (✅).
