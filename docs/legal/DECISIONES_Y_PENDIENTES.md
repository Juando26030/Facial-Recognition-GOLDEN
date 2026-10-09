# Decisiones y pendientes del bloque legal del piloto (GoldenWeb 2.0)

> Documento vivo. Los textos de la auditora están en `TEXTOS_AUDITORA_2026-10-05.md` (literales, sin editar).

## Texto para pegar en la descripción del proyecto y en el «About» de GitHub (lo pega Juan David)

**Descripción larga (proyecto en Claude):**

> GoldenWeb 2.0 es la plataforma de gestión de identidades y acceso de Golden Eventos y Logística S.A.S. para eventos presenciales: inscripción, acreditación y control de acceso por cédula, QR o reconocimiento facial voluntario, escarapelas, certificados, control de áreas e inventario, formularios web con pagos y reportes. Está hecha con FastAPI y PostgreSQL (Neon) sobre Cloud Run, y funciona también sin conexión a internet gracias a un modo de contingencia en el quiosco. Es privada por diseño (Ley 1581 de 2012): el rostro solo se usa con la autorización explícita de la persona, registrada de forma inmutable; los menores de edad quedan fuera del reconocimiento facial; lo biométrico se borra a los 7 días de finalizado el evento; y cada persona puede revocar su autorización o pedir la supresión de sus datos.

**«About» de GitHub (una línea):**

> Plataforma de gestión de identidades y acceso para eventos con reconocimiento facial voluntario, modo sin conexión, consentimiento explícito y borrado a 7 días (FastAPI, PostgreSQL/Neon, Cloud Run).

**Temas (topics) sugeridos:** `fastapi`, `postgresql`, `cloud-run`, `facial-recognition`, `access-control`, `data-protection`, `offline-first`.

## Backlog

**Hecho (6 oct 2026, requisito del piloto para el manual de consultas y reclamos):**
1. **`export-person-data`** (golden-ops, `EXPORT_CEDULA=<cédula>`): imprime un MAPA de lo que existe de esa persona (qué campos tienen dato; cuántos registros hay en eventos, accesos, formularios, pagos y consentimientos; si hay vector o foto), SIN valores personales, sin biometría y sin la cédula. No se guarda en ningún archivo ni tabla.
2. **Radicados y registro de solicitudes** (`privacy_requests`): radicado AÑO-CONSECUTIVO (2026-0001), fecha y hora, canal, titular y cédula, evento, tipo, fecha límite en días hábiles (consulta 10, reclamo 15; festivos de Colombia en `HOLIDAYS_CO`, por defecto los de 2026: confirmar cada año) y estado. Panel en Parámetros (admin y super_admin).
3. **Bandera «reclamo en trámite»**: se activa y se quita desde el panel; el sistema marca como «falta activarla» si pasan 2 días hábiles; queda el historial de quién y cuándo; al resolver o rechazar la solicitud se quita sola.
4. **Supresión de pagos**: solo `payer_email` queda en NULL; se conservan cédula, valor, fecha y referencia (ni `reference` ni `breakdown_json` llevan datos personales).

**Pendiente:**
1. **`audit-consent-purge`** (después del piloto): cómo purgar `audit_consent_logs` a los 3 años con el disparador de solo inserción: tarea de operaciones que corre con el rol dueño (nunca el de la app), desactiva el disparador SOLO dentro de su transacción (`ALTER TABLE … DISABLE TRIGGER`), borra los registros con más de 3 años y deja constancia del conteo; requiere confirmación de la auditora sobre el plazo exacto y sobre el identificador (cédula) que hoy se conserva.
4. **L7** (después del piloto): purga ordinaria de datos personales a los 90 días del cierre del evento (no toca pagos ni consentimientos).
5. **Modo A de un tercero con anexo firmado y fotos previas** (después del piloto).

## Decisiones tomadas

- Evento del piloto: propio de Golden (`controller_mode=golden`, variante 2, sin anexo).
- Dos caminos que pueden mezclarse en el mismo evento: A (cédula/QR → pantalla → clic → captura en vivo → vector por tarea) y B (`/aceptar/<evento>`, aceptación previa desde el celular).
- Sin aceptación registrada de la persona no se usa su rostro; el vector no se calcula antes de aceptar (precálculo solo con anexo firmado, solo super_admin).
- Sin coincidencia en el quiosco: no se guarda nada y se muestra el mensaje de la auditora.

## Carga de la base por título de columna y fecha de nacimiento (2026-10-08)

- **Dos formas que conviven:** columnas «opcional N» de la plantilla (el sistema pregunta qué son) y columnas con título propio. Si el título es de un campo conocido (cédula/documento, nombres, apellidos, cargo, entidad, teléfono/celular, correo/e-mail, tipo de asistente, categoría, certificado, fecha de nacimiento; sin mayúsculas ni tildes, con variantes comunes) se asigna a él; si no, se crea un campo opcional de texto con ese título (reutilizando el existente del mismo nombre al volver a cargar). Ninguna columna se ignora en silencio: el resultado lista campos reconocidos / nuevos creados / no usadas con el motivo (`app/roster_columns.py`).
- **Fecha de nacimiento:** AAAA-MM-DD, DD/MM/AAAA (el día va primero) y fecha de Excel (celda de fecha o número de serie); una ilegible es observación de la fila. Es un campo de fecha (`users.birth_date`), configurable en Parámetros del evento (etiqueta y posición), visible y editable en «Editar persona». Cambiarla a una de menor retira vector y foto.
- **Estado de registro:** cada cambio (quién, cuándo, estado anterior y nuevo; al deshacer, cuántos accesos se borraron) queda en `person_changes` (migración 0062), igual que los cambios de fecha de nacimiento. Al suprimir a la persona, el historial de estado se conserva sin su cédula y el de fecha se borra.

## Escenarios del piloto y candado «sin biometría» (2026-10-08)

- **Tres escenarios posibles para las 200 personas:** (1) base cargada por nosotros con un correo real por persona (enlace personal, llegan verificadas); (2) inscripción por formulario público, sin correo verificado (aceptación «por verificar», se confirma en la puerta); (3) sin biometría (solo cédula o QR). Guiones G1, G2 y G3 en `GUIA_PRUEBA_ACEPTACION_STAGING.md`.
- **Candado «sin biometría» por evento** (`events.biometrics_locked`, migración 0063; paso guiado): el servidor no deja activar el rostro (ni por el paso guiado ni por el interruptor), rechaza fotos en el alta manual y la carga con zip las ignora con aviso sin encender el rostro. Sin rostro: la fecha de nacimiento no existe (ni en formularios, ni en Parámetros, ni en «Editar persona»; en la carga la columna se ignora con el aviso «no se usa en este evento»), el roster local no hace consultas de consentimiento y el resumen del paso guiado dice «✅ Listo: este evento no usa biometría».
- **Correo:** hoy `app/mailer.py` envía por Microsoft Graph si existen `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` y `GRAPH_SENDER` (secretos `golden-azure-*` y `golden-graph-sender`, con sufijo `-staging` en staging); en staging faltan. Pasos para el administrador en `RUNBOOK_CLOUD_SHELL.md` sección 10. Plan B si el correo no está a tiempo: «Exportar enlaces personales» (cédula, nombre, correo y enlace) para combinación de correspondencia de Outlook o WhatsApp.
- **Contingencia (sin conexión) en producción:** apagada hasta las pruebas de dispositivos del 21 al 23 de octubre; lista de verificación y cambio exacto en `CONTINGENCIA_PRODUCCION_LISTA.md`.
- **Respuestas de la auditora** (8-oct-2026): guardadas literales en `RESPUESTAS_AUDITORA_2026-10-08.md`. Decisiones que salen de ahí: el botón de la puerta es «Entrar con mi rostro» y debajo «Ingresar con cédula o QR» (sin línea explicativa); la selfie se suelta de la memoria de la página al confirmar el servidor; el correo de constancia usa su versión optimizada.
- **Enlace personal, fecha antes de la cámara y fuente de la foto (B2a, B2e, B2c; migración 0064):** el enlace `/aceptar/<código>/<token>` identifica a la persona (token por persona y evento, revocable); si salió del listado que cargó el organizador (`accept_trusted`) abrirlo y aceptar deja la aceptación VERIFICADA (`verified_via='link'`) y entra a la matriz sin confirmación del personal; si salió de un formulario abierto sigue «por verificar». La fecha de nacimiento se valida (`/api/aceptar/<código>/check`) antes del texto y de la cámara; la selfie aparece solo después de aceptar. Fuente de la foto = el `client_photos_before` de siempre: A (el cliente entrega fotos, no se pide selfie) o B (selfie). Canal de la autorización en `audit_consent_logs.ip_or_device_id`: `web-link`, `web-qr`, `web-portal` o el dispositivo de la puerta.
- **Constancia por correo (B2b):** `app/consent_receipt.py`, tarea en segundo plano al aceptar (enlace, portal, QR o puerta); Reply-To = `PRIVACY_EMAIL`; solo eventos propios; sin correo no se envía; el texto literal va como anexo al final y solo si su huella coincide con la registrada.
- **IP y User-Agent en el registro de aceptación: NO implementado.** `audit_consent_logs` guarda solo una etiqueta (`ip_or_device_id`: `web-link`, `tablet-1`, `staff:7`…), no la IP ni el navegador. La política v1.1 menciona la IP únicamente «para limitar abusos»; no menciona el User-Agent ni su uso como prueba de la autorización ni su plazo. Para guardarlos haría falta que la política (o una cláusula expresa de la auditora) lo cubra con su finalidad y su plazo (3 años, como el registro).

## Decisiones técnicas tomadas (2026-10-06, criterio del consultor; Juan David decide solo el flujo de negocio)

- **Vector después de aceptar, siempre.** Carga masiva y alta en el quiosco guardan la foto cifrada y NO calculan el vector; se calcula por tarea (`app/enroll.py`) cuando la persona acepta (pantalla en puerta o `/aceptar`). Única excepción: evento de un tercero con pre-cálculo autorizado por un super_admin (anexo firmado). Una foto sin vector se borra igual a los 7 días (el reloj corre desde que se guarda).
- **La puerta nunca espera.** El vector se calcula aparte; mientras tanto la persona entra por cédula o QR.
- **Aceptación desde el celular = «por verificar».** No sirve para el reconocimiento hasta que el personal confirme la identidad en puerta con el documento o el QR. Código personal por correo: recomendado solo si el listado del organizador trae correos reales; no implementado.
- **Cola local de ingresos a 7 días.** Aviso amarillo desde el día 3 y rojo desde el 6; a los 7 se elimina automáticamente (texto C''') con un aviso visible, nunca en silencio. La bandeja de salida de R1 (`producto/piloto`) tenía «caducada: solo descarta una persona»: al integrar se ajusta para que a los 7 días se elimine solo, con aviso.
- **Cifrar la cola de ingresos (costo, sin implementar):** AES-GCM con clave no extraíble guardada en IndexedDB (la misma técnica de R1); el `client_id` queda en claro (llave de no duplicación) y huella, nombre, hora y método van cifrados. Cerca de 1 día con pruebas; riesgo bajo; el roster no se cifra (decisión de Juan David).
- **Clave facial obligatoria en producción:** sin `FACE_ENCRYPTION_KEY` la aplicación no arranca y no se escribe nada biométrico (falla cerrado). El bootstrap de producción ya crea el secreto `golden-face-encryption-key`.
- **Regla de borrado:** «sigue en otro evento abierto» solo cuenta donde la persona aceptó; si nunca aceptó en ninguno cuentan todos los suyos; tope de 180 días intacto. `/sistema` avisa de eventos cuyo fin pasó hace más de 3 días y siguen sin finalizar.
- **Verificar al integrar (R1):** la bandeja de salida de R1 debe quedar sin fotos ni vectores (cumple C''') y con el cifrado AES-GCM de las inscripciones nuevas.

## Nota para la auditora sobre «modificaciones de datos» sin red (texto C triple prima, no se cambia)

Sin conexión el sistema guarda en el dispositivo, cifradas, las **altas de personas nuevas** y los **ingresos** (y las decisiones de autorización); la edición de datos de personas ya existentes sin red no existe todavía, así que esa parte de la frase hoy no tiene qué almacenar.

## Cola de ingresos cifrada (hecho 2026-10-06)

La cola de ingresos, las decisiones de autorización pendientes y la lista de «revisar» se guardan cifradas en reposo (AES-GCM de 256 bits, clave no extraíble generada en el dispositivo, en un almacén aparte que sobrevive al borrado de la lista local). Solo quedan en claro el identificador del registro y su marca de tiempo (sirven para no duplicar y para vencer a los 7 días). El roster NO se cifra.

## Cálculo del vector (decisión técnica, 2026-10-06)

El cálculo corre en el servicio de biometría por una cola propia de Cloud Tasks (2 despachos simultáneos, espera creciente, mismo token OIDC), no en el servicio web. Comandos y plan de despliegue: `RUNBOOK_CLOUD_SHELL.md`.

## Paso guiado de biometría del evento (hecho)

En Parámetros del evento hay un paso guiado: 0) usará rostro, 1) Responsable (propio o tercero con razón social, NIT y correo), 2) ¿el cliente entrega fotos antes?, 3) opciones apagadas por defecto (autorización «una vez» o «cada uso», `/aceptar` con QR de cartel) y un resumen en lenguaje simple de lo que pasará en la puerta y lo que falta. **El servidor valida** (lo que protege): un evento de tercero sin los datos del organizador no activa el rostro (ni por el paso, ni por el interruptor, ni por la carga masiva); el pre-cálculo exige evento de tercero, fotos previas del cliente, referencia y fecha del anexo, la casilla de garantía del cliente y un super_admin; si el evento pasa a propio o se quitan las fotos previas, el pre-cálculo se apaga solo.

## Renombre a GoldenWeb 2.0 (en curso)

Hecho: categoría (i), texto visible (33 cambios: 27 títulos de página, encabezados de ingreso y contraseña, título de la API, asunto del correo de restablecimiento, alerta de operaciones y TESTING.md). No existe un manifest de PWA en el repositorio (no hay nada que renombrar). Pendiente de tu OK, categoría (ii): ver el reporte de casos dudosos.

## Política v1.1 ratificada (6 oct 2026) y activación

La auditora ratificó `docs/legal/POLITICA_v1.1.md` (SHA-256 `d0afc7d95083b62115ce001abeb1ab8e86925e35a14d80011e06bf75e253c844`), dejó la sección 8 como está, levantó las tres compuertas y autorizó publicarla en app.golden-eventos.com/privacidad. Datos: `RATIFICACION_v1.1.md`.

- **El archivo y su `.sha256` están congelados** (rama `producto/legal-piloto`, ruta `docs/legal/`). Una prueba falla si cambian.
- **Cómo se muestra sin tocar el archivo:** la página lee el archivo, comprueba su hash, omite el párrafo de borrador («ESTADO: PENDIENTE DE RATIFICACIÓN…») y las etiquetas «(texto de la auditora)», y agrega la leyenda «Ratificada el 6 de octubre de 2026 · SHA-256 …». Si el archivo no coincide con el hash, no se muestra y cae a la v1.0.
- **Activación:** `POLICY_VERSION=1.1`. Está en `deploy/gcp/env/common.yaml`: staging y producción la activan en cada despliegue (producción se despliega recién en el corte). La v1.0 queda histórica en `/privacidad/v1.0`.
- **La imagen** lleva el archivo ratificado (excepción en `.dockerignore` y `COPY` en el `Dockerfile`).
- La ratificación quedó completa con el nombre de la abogada y sus tres condiciones levantadas (`RATIFICACION_v1.1.md`).

## Otras decisiones de esta tanda

- **Renombre (ii) hecho:** texto decorativo de las plantillas, pie del certificado, título de las páginas legales y consentimiento de ejemplo leen `COMPANY_NAME`; `app/legal.py` no se toca (la v1.0 lleva huella). Los `alt` de los logos dicen «Logo de Golden Eventos y Logística»; la hoja de prueba de la impresora y la entidad de ejemplo de las escarapelas dicen «GoldenWeb 2.0». No se crea manifest de PWA (en iPad una app añadida a la pantalla de inicio guarda sus datos aparte de Safari y puede dejar huérfanas las colas y el roster; se evalúa después del piloto con pruebas).
- **Festivos 2026** verificados contra la lista oficial; una prueba falla si el año en curso no tiene lista cargada (`HOLIDAYS_CO`).
- **Barrido horario:** ya no ejecuta cálculos faciales (los avisa a su cola); nueva tarea `retry-face-jobs` para reintentar los agotados.
- **Push a `migra/fase1-2`: NO hecho.** El workflow `cloudrun.yml` despliega staging en cada push a esa rama y corre el Job de migraciones contra la base de staging. Se espera tu prueba en la rama de Neon y tu confirmación.

## Datos de la sociedad y cumplimiento (octubre de 2026)

- **RNBD:** el contador certificó en octubre de 2026 activos inferiores a 100.000 UVT, por lo que la sociedad **no está obligada a inscribirse en el RNBD**. Se revisa cada año (si los activos superan ese umbral, hay que inscribir las bases de datos).
- **Oficial de Protección de Datos Personales:** Paola Bocanegra. El canal público de privacidad sigue siendo **soporteit@goldenlogisticas.com** (se revisa a diario).
- **Representante legal:** Juan David Ramírez Juzga.
- **Ratificación de la política v1.1:** Dra. María Camila Morales Restrepo, T.P. 284.912 del C.S. de la J. (6 de octubre de 2026).
