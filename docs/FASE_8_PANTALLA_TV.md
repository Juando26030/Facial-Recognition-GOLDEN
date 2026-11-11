# Fase 8 · pieza 1 — Pantalla de ingreso para TV y vista móvil (9-nov-2026)

Decisión de Juan David: es solo generar la pantalla y su ruta; después se proyecta en el televisor.

- **Pantalla:** `templates/kiosk_tv.html` + `static/css/gw-tv.css` + `static/js/tv-screen.js`. Contador grande «ingresados / esperados», barra de avance y los últimos 12 ingresos (nombre + inicial del apellido + empresa; **nunca cédula**, correo ni teléfono). Logo y color de marca del evento. 16:9 a distancia; en el celular se apila en una columna (sirve como tablero móvil en vivo).
- **Dos formas de abrirla:** con sesión (coordinador+) en `/kiosk/{id}/tv`; **sin sesión** con el mismo enlace de solo lectura de las estadísticas (`/ver/tv/<token>`). «Compartir» (static/js/stats-share.js) muestra también el enlace de TV al crear el enlace del evento.
- **Estadísticas móviles:** `/ver/e/<token>` ya es responsive (hojas gw-estadisticas / p-estadisticas); la pantalla de TV es el tablero móvil en vivo del mismo enlace.
- **Datos:** `app/tv_screen.py`; el resultado se guarda 5 s en memoria (una consulta por evento por proceso, sin importar cuántas pantallas); sondeo cada 10 s y pausa si la pestaña está oculta. La persona de prueba no cuenta; una edición («Actualizado») no es ingreso.
- **Rutas nuevas:** `GET /ver/tv/{token}`, `GET /api/ver/{token}/tv`, `GET /api/ver/{token}/logo` (solo logo propio), `GET /api/events/{id}/tv` y `GET /kiosk/{id}/tv`. Todas `def`, `no-store`, `noindex`, con el límite por IP de los enlaces. Sin migración.
- **Pruebas:** `tests/test_pantalla_tv.py` (no corre aquí: la suite está bloqueada hasta el 11-nov). Revisado: py_compile, ruff, jinja, `node --check` y captura a 1920×1080 y 390 px.
