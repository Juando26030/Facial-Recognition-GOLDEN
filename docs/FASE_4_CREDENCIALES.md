# Fase 4 — Entrega de credenciales del personal por correo

Rama `f4/credenciales-correo`. Decisión del dueño: los digitadores temporales ingresan SOLO con su cédula y el coordinador los autoriza (S1, `app/login_control.py`); no hay contraseña que entregar.
La entrega es por **correo** (sin WhatsApp ni SMS) y existe la **hoja impresa**. Ningún correo lleva contraseñas.

## Qué existía antes
- `app/mailer.py` (`send_mail`, `clean_subject`), correos de constancia (`consent_receipt`), enlaces personales (`acceptmail`), reimpresión (`reprint`): todos como trabajos de `app/jobs.py`.
- Cuentas: `POST /api/staff` (admin crea coordinador/comercial/admin con la contraseña que escribe; el teléfono es obligatorio), `PUT /api/staff/{id}/password`, y para digitadores `POST /api/events/{id}/staff-users` (usuario = contraseña = cédula), `assign-existing` y el Excel `import`.
- Ningún aviso por correo al crear, reiniciar o asignar; las cuentas temporales no tenían correo (el Excel y el alta no lo pedían); no había hoja imprimible.
- El cambio obligatorio de contraseña en el primer ingreso (`must_change_password`, `/cambiar-contrasena`) ya existe; lo endurece otro agente en otra rama (middleware/auth.py: NO se tocan aquí).

## Qué hace ahora
- `app/staff_credentials.py`: contenido (`render`), encolado idempotente (`enqueue`, `dedupe_key = staff_credentials:{modo}:{cuenta}:{evento}:{nonce}`) y manejador `staff_credentials` (cola general; registrado en `jobs.GENERAL_KINDS`/`HANDLER_MODULES`). Se encola en la MISMA transacción de la acción y luego `jobs.kick()`. El trabajo solo guarda ids y banderas (nada personal).
- Correos (siempre sin contraseña, enlace = `PUBLIC_BASE_URL` + `/login`, siempre https salvo localhost; sin enlaces con tokens):
  - Digitador: «ingresa con tu cédula; el coordinador del evento te autorizará al llegar» + datos del evento (nombre, fecha, lugar, coordinador).
  - Resto de roles: «tu contraseña inicial es tu número de documento» (si lo es; si no, «te la comunicó quien creó tu cuenta») y «el sistema te pedirá cambiarla en tu primer ingreso».
- Cuándo se encola (un correo por acción; sin correo válido no se encola y la respuesta trae `credentials_mail: "no_email"`):
  - Crear cuenta de personal (`POST /api/staff`): modo `created`. Desde ahora esa cuenta nace con `must_change_password = true`.
  - Restablecer contraseña (`PUT /api/staff/{id}/password`): modo `reset`, una vez por restablecimiento (nonce = `session_epoch`).
  - Crear digitador en el evento, asignar uno existente o subir el Excel (columna opcional «Correo (opcional)»): modo `created`/`assigned`, una vez por persona y evento.
- Interruptor por evento `events.staff_mail_enabled` (migración `0100_event_staff_mail`, por defecto encendido): casilla en «Usuarios del evento» (`PATCH /api/events/{id}/staff-mail`, auditado). Se vuelve a leer al enviar: si se apaga con trabajos en cola, no salen.
- Reenviar: `POST /api/events/{id}/staff-users/{staff_id}/resend-credentials` (coordinador+, no la comercial pura, solo sus eventos por `get_event_for_staff`) y `POST /api/staff/{id}/resend-credentials` (cuentas que no son de digitador y aún no eligieron su contraseña, quien puede administrarlas). Tope **3 por persona cada 24 h** contado en `audit_actions` (acción `resend_credentials`, solo ids, sin nombre ni correo), bajo candado de fila. Responde 400 sin correo, 429 al pasar el tope.
- Correo del digitador: campo en el alta, columna en el Excel y `PATCH /api/events/{id}/staff-users/{staff_id}/email` («Agregar correo» en la tarjeta).
- Hoja impresa: `GET /kiosk/{id}/usuarios/hoja` (coordinador+, no comercial): nombre, cédula como usuario, columna «Recibido» e instrucciones; sin contraseñas. Hoja A4 normal por el cuadro de impresión del navegador (`window.print()` desde `static/js/hoja-credenciales.js`; sin `--kiosk-printing`). CSS propio `static/css/gw-hoja-credenciales.css`. No toca nada de la impresión de escarapelas ni `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`.

## Seguridad
Asunto por `clean_subject`; nombres y evento escapados en el HTML; nada de datos personales en logs/auditoría/cola; reenvío con tope; un coordinador solo opera sobre sus eventos; la cédula en el correo es el usuario (no es secreto), y por eso el ingreso del digitador sigue exigiendo la autorización del coordinador.

## Pruebas
`tests/test_fase4_credenciales.py` (corren en CI con la base de pruebas): un solo correo por creación/restablecimiento/asignación, sin contraseñas, digitador vs. resto, sin correo, tope de reenvío y auditoría, permisos, evento ajeno, interruptor, hoja impresa.

## Pendiente / riesgos
- Si `PUBLIC_BASE_URL` falta, el correo dice «la dirección web que te indique tu coordinador» (y la hoja igual).
- El texto «contraseña inicial = documento» solo se afirma cuando de verdad lo es (se comprueba al crear/restablecer/reenviar).
