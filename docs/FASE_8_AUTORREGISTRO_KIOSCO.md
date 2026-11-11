# Fase 8 · Pieza 3 — Autorregistro sin base de datos en el kiosco

**Qué es.** Una pantalla aparte, `/kiosk/{evento}/autoregistro`, para eventos SIN lista de invitados: la persona se crea sola (cédula, nombres y lo que el evento haya marcado como obligatorio). Es una versión mínima de «Registrar nuevo».

**Cómo se usa.**
1. Parámetros del evento → «Autorregistro sin base de datos» → encender (apagado de fábrica). Lo hace coordinador o administrador.
2. Con el evento «En proceso», en el equipo del kiosco (abierto con una cuenta del personal) se abre la pantalla; también hay un enlace en Registro cuando está encendido.
3. Cada persona escribe sus datos y pulsa «Registrarme». La pantalla se reinicia sola a los 6 s, o a los 90 s sin tocarla.

**Reglas.**
- Reutiliza el alta de siempre (`_manual_register`): mismas validaciones, origen «Autoregistro» y método de registro «autoregistro» en reportes.
- Solo pide cédula, nombres y los campos **obligatorios** de Parámetros → campos. Si hay un obligatorio que la pantalla no sabe pedir (p. ej. firma), no deja encender el interruptor y dice cuál hay que volver opcional.
- **No capta rostro ni foto.** La autorización biométrica la da la persona en la pantalla de la auditora, no aquí. Menores: sin biometría por diseño.
- No muestra ni busca a otras personas. Si la cédula ya estaba registrada, dice «Ya quedaste registrado» sin ningún dato; un caso especial (p. ej. persona con supresión) recibe un mensaje neutro que manda al punto de ayuda.
- Límite por equipo y evento: 40 registros cada 10 minutos (`SELFREG_MAX_PER_10MIN`; contador en memoria del proceso).
- Solo con el evento «En proceso» (misma puerta de registrar). El registro touch NO se tocó.

**Piezas.** `app/selfreg.py` (campos y límite), `app/routers/selfreg.py` (`GET /api/events/{id}/selfreg/form`, `POST …/selfreg`, `GET/PUT …/selfreg-config`), `templates/kiosk_autoregistro.html`, `static/js/selfreg.js`, `static/css/gw-autoregistro.css`, migración `0115_kiosk_selfreg` (`events.selfreg_enabled`), `tests/test_autorregistro_kiosco.py`.

**Pendiente (no es de código).** El aviso de tratamiento de datos personales para esta pantalla debe venir **literal de la auditora**; hoy la pantalla solo enlaza a la Política de Privacidad vigente. Hasta tener ese texto, no usarla con datos sensibles. Pruebas pytest escritas pero sin correr (se corren una sola vez en Cloud Shell al final).
