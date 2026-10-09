# Registros y auditoría: plazo de borrado actual y dónde corre (2026-10-09)

Levantada leyendo el código de la rama `producto/envio-enlaces`. «Sin purga» = no encontré ninguna regla automática que la borre. Solo `accept_mail_log` se cambió en esta entrega; el resto queda como estaba, para que lo decida Juan David.

| Tabla | Qué guarda | Plazo de borrado ACTUAL | Dónde corre |
|---|---|---|---|
| `accept_mail_log` | Envíos del enlace personal: cédula, fecha y hora, resultado (sin IP, sin User-Agent, sin correo) | **60 días calendario desde la fecha de cada fila** (constante `LOG_RETENTION_DAYS`, `app/acceptmail.py`) | Job horario `golden-ops`, paso `purge` (`app/ops_runner.py` → `acceptmail.purge_log`) |
| `audit_consent_logs` | Prueba de la autorización: cédula, fecha, versión, huella del texto, decisión, etiqueta de dispositivo | **Sin purga.** Solo INSERT (disparador y REVOKE); la política promete conservarla 3 años; hoy nada la borra ni a los 3 años | — |
| `web_acceptances` | Aceptación hecha desde el celular: fecha, si fue verificada y cómo | **Sin purga** (no la toca ni la purga de 7 días ni la de 60) | — |
| `event_attendees.accept_token` | El enlace personal (token) de cada persona | Se borra con la fila del asistente al suprimir a la persona; si no, queda. El enlace deja de servir al finalizar el evento (404) | Supresión individual (`app/privacy.py`) |
| `system_events` | Hechos del sistema: errores 5xx, último webhook de Wompi, alertas enviadas, descargas de enlaces; sin datos personales | **Sin purga** | — |
| `rate_limit_events` | Intentos para limitar abusos: clave e **IP** | **1 día** | Limpieza oportunista en cada escritura (`app/security.py`, `record_event`), dentro de la petición; no es un Job |
| `password_reset_tokens` | Códigos de restablecimiento del personal | **Sin purga** de los vencidos o usados (se invalidan, no se borran) | — |
| `access_logs` | Ingresos marcados en puerta | **Sin plazo.** Se anonimizan al suprimir a la persona (`user_id` en NULL) y se borran al quitarla del evento o deshacer su registro | Supresión individual y acciones del personal |
| `person_changes` | Cambios manuales de estado y de fecha de nacimiento | **Sin plazo.** Al suprimir a la persona: el de estado se anonimiza, el de fecha de nacimiento se borra | Supresión individual (`app/privacy.py`) |
| `privacy_requests`, `privacy_request_counters` | Solicitudes de Habeas Data y su consecutivo | **Sin purga** | — |
| `suppressed_people` | Huella de la cédula de quien pidió supresión (para no recargarla) | **Permanente** (a propósito) | — |
| `jobs`, `bulk_jobs` | Cola de trabajos y cargas masivas (sin datos personales en el texto) | **Sin purga** de los terminados | — |
| `form_payments`, `form_refunds` | Registros contables de pago | Política: 10 años, bloqueados. **Sin purga automática**; el correo de pago se borra al suprimir | Supresión individual |
| `form_submissions` | Inscripciones por formulario | **Sin plazo.** Al suprimir a la persona se vacía el contenido | Supresión individual |
| `print_logs`, `area_movements`, `inventory_deliveries` | Impresiones, movimientos por área, entregas | **Sin plazo.** Se borran por persona al suprimirla | Supresión individual |
| `users` (campos biométricos: foto, vector, fecha de consentimiento) | Rostro de la persona | **7 días tras finalizar el evento** (tope 180 días desde la captura) | Job horario `golden-ops`, paso `purge` (`app/privacy.py`, `purge_expired`) |

**Fuera de las tablas:** el historial de la base en Neon (1 día), las versiones viejas de las fotos en el bucket (1 día) y las copias de seguridad (hasta 30 días).

**Pendiente conocido:** la política v1.1 promete suprimir o anonimizar los datos identificativos y de contacto a los 90 días del cierre del evento. Eso es la pieza **L7**, aplazada para después del piloto (`DECISIONES_Y_PENDIENTES.md`); hoy no hay una purga que lo cumpla.
