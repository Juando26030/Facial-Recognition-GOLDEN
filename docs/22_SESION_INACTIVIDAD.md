# Cierre de sesión por inactividad (3-nov-2026)

Evita sesiones olvidadas que mantienen la base (Neon) despierta. Solo personal (staff); no toca formularios públicos, impresión, webhooks ni `/internal/*`.

- **Tiempo general:** `SESSION_IDLE_MINUTES` (10 por defecto; 0 = apagado).
- **Por evento:** Parámetros del evento → «Cierre de sesión por inactividad» (5 a 60 min; vacío = general). Solo rige con el evento **en proceso** y para quien trabaja en él; si no, rige el general. Columna `events.idle_minutes` (migración aditiva `0081_event_idle_minutes`; se eligió columna porque el único JSON del evento es el de impresión, que no se toca). Va ANTES que el código (Job de migraciones primero).
- **Dónde vive la actividad:** en la cookie de sesión firmada (`la` = última acción real, `idle_m` = minutos del evento, `idle_off` = cuenta exenta). Cero consultas a la base; compatible con el pooler de Neon. Lo aplica el middleware `idle_gate` (`app/main.py`, lógica en `app/idle.py`) en cada petición: vencida → se borra la sesión; páginas redirigen a `/login?expirada=1`, llamadas reciben `401 {"detail":"session_expired"}`.
- **Qué cuenta como uso:** solo navegaciones del navegador y `POST /api/session/touch`, que `static/js/idle-session.js` manda (máx. 1 cada 30 s) cuando hubo clic, teclas, toque o scroll. Los sondeos (`/api/session/ping`, directorio, estadísticas, sistema, analítica…) y `GET /api/session/idle` nunca renuevan; `X-Gw-Passive: 1` lo declara explícitamente.
- **Aviso:** 1 minuto antes, toast «Tu sesión se cerrará por inactividad…» con «Seguir conectado». Al vencer se llama a `/logout` y se lleva al login con mensaje.
- **Sin conexión:** el cliente no avisa ni cierra si no hay red o el servidor no responde; la cola offline (IndexedDB) no se borra. Si el servidor ya venció la sesión, al volver la red el primer llamado recibe 401 y se pide iniciar sesión; los ingresos pendientes se envían después (igual que `session_replaced`).
- **Exentos:** cuentas de «Puesto de impresión» y las que atienden la impresión de otros equipos (sin toques en pantalla). Sesiones anteriores al despliegue (sin `la`) no se expulsan.
- **Pantallas con el script:** las que cargan `toast.js` salvo `impresion_usb`. Escarapela, formularios públicos y certificados no lo cargan.
- **Límites conocidos:** una petición lenta que empezó antes de un `touch` puede reescribir la cookie con una marca algo más vieja (segundos); `kiosk_ruleta_visual` sin ningún clic vence como cualquier otra pantalla.
- Pruebas: `tests/test_idle_session.py`, `tests/js/idle_session_check.js`.
