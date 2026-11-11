# Fase 5 · Notificaciones y avisos de inventario (9-nov-2026)

Decisión de Juan David: cada usuario tiene **notificaciones dentro de la aplicación** (campana) **y** por **correo** (el que tiene registrado). La reserva de inventario **nunca bloquea** la creación de un evento: solo avisa.

## Módulo de notificaciones
| Pieza | Dónde |
|---|---|
| Tabla `notifications` (una fila por cuenta y aviso; `dedupe_key` evita repetir) y columna `inventory_products.qty_total` | `app/models.py`, migración `0110_notifications` |
| Crear avisos: `notifications.notify(db, ids, kind=, title=, body=, url=, event_id=, dedupe_key=)` (no confirma; después `jobs.kick()`) | `app/notifications.py` |
| Correo por la cola general (`notification_mail`; no envía a cuentas sin correo, inactivas o archivadas) | `app/notifications.py` |
| API de la campana (solo las propias): `GET /api/notifications`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all` | `app/routers/notifications.py` |
| Campana (botón flotante abajo a la derecha, sin sondeo: carga al abrir la página y al pulsarla) | `static/js/notifications.js`, `static/css/gw-notifications.css`; incluida en el menú lateral, `/inventario` y el inicio |
Cualquier módulo nuevo que quiera avisar a alguien usa `notifications.notify`. No lleva datos personales de asistentes.

## Avisos de inventario (`app/inventory_alerts.py`)
1. **Anticipación:** evento en la ciudad de la bodega (`INVENTORY_HOME_CITY`, por defecto Bogotá; sin ciudad se asume la misma) → reservar con ≥ **1 día**; otra ciudad → ≥ **7 días** (envío).
2. **Material:** con **existencias** del producto (`Existencias de Golden` en Configuración → Inventario; vacío = sin control), si lo asignado a este evento + lo asignado a otros eventos que se cruzan en fechas (no finalizados ni archivados) las supera → «no hay material de Golden: faltan N; alquilar o buscar otras opciones».
- Destinatarios: todas las cuentas de **almacén**, la **comercial** y el **coordinador** del evento (no quien hizo el cambio). Se dispara al guardar el inventario del evento; el bloque de inventario también muestra los avisos. El mismo aviso no se repite mientras no cambie la situación.
- **Nunca bloquea** (ni la creación del evento, ni «En proceso» por esto). Lo único que bloquea es el cuadre exacto ya decidido.

## Pendiente / no verificado
No se corrió pytest ni la migración (sin Postgres aquí): verificado con `py_compile`, `ruff` y `node --check`. Pruebas: `tests/test_notificaciones_inventario.py`. Falta mirar la campana y el aviso en el navegador (staging). Los avisos por cambio de **fechas** del evento (sin tocar el inventario) y un recordatorio diario no están: hoy se evalúa al guardar el inventario.
