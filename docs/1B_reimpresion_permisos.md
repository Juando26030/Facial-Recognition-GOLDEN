# Fase 1B · Reimpresión configurable por evento, con permisos

Decidido con Juan David (dueño), 2026-11-05. Rama `feat/1b-reimpresion-permisos`. Migración `0083_reprint_requests` (solo aditiva).

## Qué hace
Cada evento tiene un parámetro **Reimpresión** (Parámetros > Impresión y escarapela; solo admin o super_admin lo cambia):

| Modo | Qué pasa cuando alguien intenta reimprimir a una persona que YA se imprimió |
|---|---|
| **Habilitada** (por defecto) | Como hoy: solo avisa «Ya se ha impreso esta escarapela… ¿Deseas imprimir de nuevo?». |
| **Deshabilitada** | «No se puede reimprimir» y debajo «¿Es una emergencia autorizada? Solicitar permiso». Sin permiso, el servidor rechaza (403). |
| **Deshabilitada + permiso** | El coordinador del evento aprueba: vale UNA reimpresión de ESA persona, para ese digitador, y vence (15 min por defecto). |

La primera impresión de una persona nunca se bloquea. Un coordinador asignado a ese evento y los admin/super_admin no necesitan permiso (son quienes lo dan). Cualquier otro coordinador sí lo pide (la 1A los deja entrar a todos los eventos, pero decidir es solo del coordinador asignado).

## Decisiones de diseño (y por qué)
1. **Modo del evento = columna `events.reprint_disabled`** (BOOLEAN NOT NULL DEFAULT false). El evento no tiene un JSON de configuración general (`print_settings_json` es de valores de impresión y es intocable), y una columna con DEFAULT constante no reescribe la tabla en Postgres 11+.
2. **Quién recibe:** solo el coordinador asignado (`Event.coordinator_staff_id`). Si el evento no tiene (o está inactivo), los admin/super_admin activos. Si el coordinador no tiene correo, el correo va a los admin (mejor que perder la solicitud).
3. **Cómo se sabe si el coordinador tiene sesión activa** (no existía un «visto por última vez»; no se agregó una escritura frecuente): la pantalla del coordinador sondea cada 10 s (`GW.poll`, pausa a los 60 s sin uso) y, al ver una solicitud, la marca `screen_seen_at` (una sola escritura por solicitud). Dos trabajos diferidos en la cola de siempre (`app/jobs.py`, `run_at` + `kick(at)`):
   - **a los 25 s** (`reprint_notify`/presence): si NINGUNA pantalla la mostró → no hay sesión activa (o está inactiva) → correo ya.
   - **a los 2 min** (`reprint_notify`/timeout): si sigue pendiente → correo.
   La reserva del envío es un UPDATE atómico de `email_sent_at`: aunque corran los dos trabajos, sale un solo correo por destinatario (`reprint_mail`, `dedupe_key`).
4. **Enlace del correo** (`/reimpresion/<token>`): token de 256 bits (`secrets.token_urlsafe(32)`), guardado SOLO como SHA-256 (`reprint_links`), ligado a una solicitud y a un destinatario. El **GET solo muestra** (los escáneres de correo abren enlaces); aprobar o negar es un **POST** (el middleware CSRF revisa `Origin`). El enlace se gasta con un UPDATE atómico; al decidirse la solicitud (por pantalla o por correo) o vencer, todos sus enlaces mueren. Enlace desconocido, usado, vencido o de solicitud ya respondida = la MISMA página 410 (no se confirma nada a quien adivina). Cabeceras `no-store`, `no-referrer`, `noindex`. La ruta está exenta del cierre por inactividad (no hay sesión) y se sirve desde el servicio `web`.
5. **Puerta en el SERVIDOR:** `reprint.gate()` — en `POST /api/events/{id}/print-jobs` (cola compartida) aunque el JS lo permita, y en `POST …/reprint-requests/use` (impresión en el propio equipo: USB o ventana de Chrome). El permiso se gasta con `UPDATE … WHERE status='approved' AND used_at IS NULL AND expires_at > ahora`: dos equipos no lo usan dos veces. En la cola compartida el gasto va en la misma transacción que crea el trabajo (si algo falla después, vuelve).
6. **Vigencias:** `REPRINT_APPROVAL_MINUTES` (15) una vez aprobado; `REPRINT_REQUEST_MINUTES` (10) la solicitud sin respuesta. Todo en UTC; hora local solo al mostrar.
7. **Anti-abuso:** máx. 3 solicitudes vivas por persona del personal y evento (429), separadas ≥5 s, máx. 12 por hora. Pedir de nuevo a la misma persona devuelve la solicitud viva. Un digitador de otro evento recibe el 403 de siempre.
8. **Auditoría** (`reprint_audit`, solo se agregan filas): `requested`, `screen`, `email` (a quién), `email_none`, `approved`, `denied`, `expired`, `used` — con quién, cuándo y canal (`screen`/`email`/`shared`/`local`). La ve en Parámetros (Solicitudes de permiso) el coordinador del evento o admin+; `GET /api/events/{id}/reprint-requests`. Sin cédulas ni nombres en el log. Si se borra a la persona del evento, se borran sus solicitudes (cascada a su auditoría).
9. **Sondeo barato:** una consulta indexada cada 10 s por pantalla de coordinador ACTIVA; el sondeo del digitador solo corre mientras su cuadro está abierto esperando. Los dos van con `X-Gw-Passive` (no renuevan la sesión) y respetan `GW.idle`. Sin WebSockets.
10. **Sin conexión:** «Para pedir permiso necesitas conexión.» (aviso y bloqueo del botón).
11. **Límites conocidos:** (a) la impresión AUTOMÁTICA al registrar no pide permiso (es la primera impresión; si se deshace y se vuelve a acreditar a alguien ya impreso, sale sola — la ventana de 30 s ya existente la frena solo en ese lapso). (b) Una impresión local sin red no se puede validar contra el servidor; la compartida sí siempre. (c) El permiso es del digitador que lo pidió.

## Flujo
1. Digitador toca Imprimir/Reimprimir (botón, Cola o ficha) de alguien ya impreso → `print-count` trae `reprint_locked`, `permit`, `request`.
2. Deshabilitada y sin permiso → cuadro «No se puede reimprimir». **Solicitar permiso** → `POST /api/events/{id}/reprint-requests` (pendiente). Se encolan los dos avisos diferidos.
3. Pantalla del coordinador: tarjeta (evento, quién pide, a quién, hora) con **Aprobar / Negar** → `POST /api/reprint-requests/{id}/decision`.
4. Si no la vio en 25 s o no respondió en 2 min → correo con enlace de un solo uso → página de confirmación → botones → POST.
5. El digitador ve por sondeo: esperando / aprobada («Reimprimir ahora») / negada / vencida.
6. Al imprimir (cola compartida o local) el servidor gasta el permiso. Segundo intento = 403.

## Textos
**Pantalla del digitador:** título «No se puede reimprimir». Aviso: «La reimpresión está deshabilitada en este evento. A esta persona ya se le imprimió su escarapela.» Pregunta: «¿Es una emergencia autorizada?» Botones: Cancelar · Solicitar permiso. Esperando: «Esperando respuesta del coordinador. Ya le avisamos en su pantalla y, si no responde pronto, por correo. Puedes cerrar este cuadro: te avisamos aquí cuando responda.» Aprobada: «Permiso aprobado. Vale para una sola reimpresión y vence a las HH:MM.» [Reimprimir ahora]. Negada: «El coordinador negó el permiso. No se reimprime esta escarapela.» Vencida: «El permiso venció. Si sigue siendo una emergencia, puedes pedirlo de nuevo.» Sin red: «Para pedir permiso necesitas conexión.» Servidor (403): «No se puede reimprimir: esta escarapela ya se imprimió y la reimpresión está deshabilitada en este evento. Pide permiso al coordinador.»

**Pantalla del coordinador:** «Permiso para reimprimir» · Evento · Lo pide · Escarapela de · Hora del pedido · «Si apruebas, se podrá reimprimir una sola vez y el permiso vence pronto.» · [Negar] [Aprobar].

**Correo** — Asunto: `Permiso de reimpresión pedido en {evento}`.
> Hola {nombre}, {digitador} pidió permiso para reimprimir la escarapela de {persona} en el evento «{evento}» (pedido a las {HH:MM}). En este evento la reimpresión está deshabilitada y esa persona ya tiene su escarapela impresa.
> Para responder abre este enlace. Sirve una sola vez y vence a las {HH:MM}: {enlace}
> Al abrirlo verás los datos y dos botones: Aprobar o Negar. Abrir el enlace no aprueba nada. Si no esperabas este correo, ignóralo: sin tu respuesta no se imprime nada. — Golden Eventos y Logística

**Página del enlace:** «Permiso para reimprimir una escarapela» (Evento, Lo pide, Escarapela de, Hora del pedido) · «Si apruebas, se podrá reimprimir una sola vez y el permiso vence en 15 minutos.» · Aprobar / Negar. Resultados: «Permiso aprobado…», «Permiso negado…». Enlace muerto: «Este enlace ya no está disponible. Ya se usó, venció o la solicitud ya fue respondida. Si hace falta, pide una nueva desde el Registro.»

## Prueba física con la Brother (la hace Juan)
No se tocó ningún parámetro de impresión (62 × 99,8 mm, 96 mm de imagen, margen 0,5 mm, marca de fin, Chrome normal con su cuadro): `tests/test_impresion_parametros_fijos.py` sigue intacto. Aun así, tres configuraciones con la impresora real, en un evento de prueba con impresión compartida y un digitador sin impresora (X) que imprime en el equipo de otro (Y):
1. **Habilitada** (por defecto): imprimir a una persona; imprimir otra vez → aviso «ya se imprimió», aceptar → sale una segunda escarapela idéntica.
2. **Deshabilitada** (admin en Parámetros > Reimpresión > Guardar): repetir → «No se puede reimprimir». Comprobar que NO sale nada, ni por el botón, ni por la Cola, ni intentando de nuevo.
3. **Deshabilitada + permiso:** X pide permiso. Con el coordinador del evento en pantalla: aparece la tarjeta; Aprobar → X ve «Permiso aprobado» → «Reimprimir ahora» → sale UNA escarapela (misma medida y marca de fin que siempre). Repetir el intento → bloqueado de nuevo. Después: (a) sin sesión del coordinador, esperar 25 s: debe llegar el correo; abrir el enlace (no debe aprobar nada), Aprobar, reimprimir; el mismo enlace otra vez → «ya no está disponible». (b) Negar → no sale. (c) Dejar vencer (>15 min) → no sale.
Revisar la auditoría en Parámetros > «Solicitudes de permiso de este evento».

## Configuración / despliegue
Variables nuevas (opcionales): `REPRINT_APPROVAL_MINUTES` (15), `REPRINT_REQUEST_MINUTES` (10). El correo usa `app/mailer.py` (Graph/SMTP ya configurados; sin ellos queda `.eml` en `data/outbox/`). Requiere `PUBLIC_BASE_URL` para armar el enlace. Migración `0083` (aditiva, con downgrade): se aplica con el Job de migraciones como siempre; NO se aplicó en producción.
