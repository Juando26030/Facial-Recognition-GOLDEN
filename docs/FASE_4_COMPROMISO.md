# Fase 4 — Compromiso digital del digitador por evento

Rama `f4/compromiso` (migración `0100_event_staff_pledge`, encadenada a `0099_digital_badge_fields`). Texto del compromiso: el del PDF «Compromiso digital del digitador» de Golden (`app/pledge_texts.py`, literal).

## Qué hace
- **Un formulario por evento**, con su enlace en «Usuarios temporales» (copiar, generar/cambiar, revocar; vale hasta que el evento finaliza). Lo administra el coordinador del evento (y el cliente) y admin+. **Nunca la comercial.**
- **Camino A:** el digitador abre el enlace, llena los datos (cédula, nombre, celular, contacto de emergencia, encuesta Sí/No), marca la declaración y dibuja su firma. Al enviar se crea la cuenta temporal (usuario = cédula, contraseña inicial = cédula, como el Excel) o se reutiliza la que exista, y se asigna al evento. El coordinador solo la autoriza.
- **Camino B/C:** una cuenta asignada al evento que ingresa con su cédula y no tiene el compromiso de ESE evento va, **antes de la fila de espera**, al mismo formulario (ya identificada). Al firmar pasa a la fila y el coordinador la ve para autorizar. El compromiso es por evento, sin vigencia de 30 días.
- **Respuestas críticas no bloquean:** «No» a condiciones claras o a asistencia → alerta en la fila del coordinador; «Sí» a una pregunta de salud → «Tiene información de salud» (abrir el detalle queda en `audit_actions`: quién y cuándo, sin datos).
- **Sin compromiso no se autoriza el ingreso:** `decide_login` responde 409 y la lista no ofrece «Permitir». No se tocó la lógica de «autorizar todos los pendientes».

## Qué se reutilizó del motor de formularios web
Tabla `web_forms` (`kind='pledge'`), `formlib.sanitize_design` / `validate_submission` (los campos del PDF son campos normales), página pública `/f/{evento}/{enlace}` con `/state` y `/submit`, `form-render.js` y `form_public.html`, token de etapa (itsdangerous), archivos del formulario (`form_file_key`, la firma es un archivo), idempotencia por `sid`, límite por IP del motor, caché pública, CSRF por Origin, cierre por estado (`manual_status`), borrado por evento.

## Qué se extendió (mínimo, un punto de entrada cada uno)
| Extensión | Dónde |
|---|---|
| Campos `sensitive`: salen de `data_json` y van cifrados (`FACE_ENCRYPTION_KEY`) en `form_submissions.sensitive_json` | `formlib.sanitize_design`, `formsvc.split_sensitive`, `forms_public._reserve_and_store` |
| Campo de archivo `capture='signature'` (lienzo táctil → PNG ≤ 200 KiB con trazo) | `form-render.js`, `formlib`, `pledge.signature_problem` vía `_check_upload` |
| Gancho `on_confirmed`: cuenta temporal + asignación + evidencia + documento, en la misma transacción | `forms_public` → `pledge.on_confirmed` |
| Vigencia del enlace = evento en curso; bloqueo si falta el texto de la auditora | `formsvc.public_state` → `pledge.public_state` |
| Purga a los 30 días | `formsvc.purge_sensitive`, paso `purge` del Job de ops, `privacy.erase_person` |
| Puerta en el login (B/C) y bloqueo de aprobación | `routers/auth.py`, `routers/login_approval.py` |
| El formulario no alimenta la base del evento ni aparece en la API normal de formularios | `formsvc.confirm_submission`, `routers/forms.py` |

Tabla propia `event_staff_pledges`: evidencia por evento y persona (fecha UTC, IP enmascarada, versión del texto, huella SHA-256 del texto + respuestas + hash de la firma, llave de la firma y del documento, banderas). Única vigente por (evento, persona); volver a firmar solo si el coordinador lo permite (`allow-resign`), y la firma anterior queda como historial.

## Datos sensibles y retención
Salud, medicación, apoyo emocional y contacto de emergencia: cifrados, solo los ve el coordinador del evento/cliente y admin+ (de a una persona, auditado), **jamás** en listados, exportaciones, reportes, logs ni en el documento firmado. Se borran `FORM_PLEDGE_HEALTH_RETENTION_DAYS` (30) días después de finalizar el evento, con tope de `FORM_SENSITIVE_MAX_DAYS` (180) desde el envío. Sin llave de cifrado en producción el envío falla cerrado (503). El documento firmado y la evidencia permanecen.

## Seguridad
Enlace de 144 bits comparado con `safe_eq`; límite por enlace y por IP (`PLEDGE_LINK_MAX_PER_HOUR`, `PLEDGE_IP_MAX_PER_10MIN`) más el del motor; tope de cuerpo del motor; cédulas normalizadas y nombres sin `<>`; **sin enumeración**: éxito, cédula de otra clase de cuenta y compromiso ya firmado responden igual (y bcrypt se paga siempre); `no-store`; el enlace se enmascara en logs (`obs.mask_url`); `audit_actions` sin datos personales; CSP intacta (sin bloques `<script>` nuevos).

## Lo que falta de la auditora (PENDIENTE_AUDITORA)
El **texto de autorización de tratamiento de datos sensibles** (`SENSITIVE_AUTH_TEXT`) es un borrador. `APPROVED=False`: en producción el enlace responde «no disponible» salvo `PLEDGE_ALLOW_DRAFT_TEXT=1` (staging/pruebas lo permiten solos). Con `PLEDGE_REQUIRE_SENSITIVE_AUTH=0` el formulario no pide datos sensibles y puede publicarse sin ese texto. Al llegar el texto: pegarlo literal, poner `APPROVED=True` y cambiar `SENSITIVE_AUTH_VERSION`; el diseño se reconstruye solo y las firmas anteriores conservan la huella de lo que vieron.

## Límites conocidos
- No hay librería de PDF: el «documento generado» es HTML imprimible (el navegador lo guarda como PDF).
- La firma es dibujada (puntero/táctil); no hay alternativa por teclado.
- Activar el compromiso no cierra sesiones ya iniciadas; aplica al próximo ingreso.
- Si se revoca el enlace, las cuentas que deben firmar al ingresar ven «todavía no está disponible» hasta regenerarlo.
- «Persona» = cuenta de digitador (`StaffUser`).
- Las vistas de admin+ se auditan pero no piden confirmación extra.
- Pruebas: `tests/test_pledge.py` (necesita Postgres, corre en CI).
