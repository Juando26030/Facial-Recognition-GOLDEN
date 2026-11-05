# Cierre de las Fases 0 y 1 — 5-nov-2026

Cierre confirmado por Juan David por escrito (conversación del 5-nov-2026, 15:30 hora de Bogotá): fases **0A, 0B, 0C, 1A y 1B cerradas**. Sus pruebas reales (Excel real, formulario de persona sin red, Registro en celular/tablet, digitador con engranaje, medición de tiempos con digitadores nuevos y las tres configuraciones de reimpresión con la Brother) las hizo él y pasaron. Los tiempos por registro mejoraron de forma clara.

## Tablero
| Fase | Estado | Cierre |
|---|---|---|
| 0A · Cierre del piloto | cerrada | 5-nov-2026 |
| 0B · Limpieza y orden del repositorio | cerrada | 5-nov-2026 |
| 0C · Línea base de seguridad | cerrada | 5-nov-2026 |
| 1A · Puerta rápida | cerrada | 5-nov-2026 |
| 1B · Impresión con permisos | cerrada | 5-nov-2026 |
| 2 · Diseño y calendario | siguiente (no iniciada) | — |

## Qué salió a producción con el cierre (despliegue del 5-nov, 9 pm, con autorización de Juan David)
- Búsqueda del Registro con errores de tipeo, cédula por últimos dígitos, caja vacía al acreditar, papelera, «Registrar nuevo» en blanco, «Recién creado».
- Origen «Alta manual» renombrado **«Creado nuevo»** (fila, filtro, Excel y estadísticas); el estado sigue siendo solo Registrado / No registrado.
- Contador de arriba del Registro: «Total» o el origen filtrado.
- «Más → Eliminar» solo desde coordinador (el digitador temporal ya no lo ve).
- Evento en «creado»: no se registra (tampoco por Editar → Guardar) ni se imprime.
- Persona **«PRUEBA»** en cada evento nuevo (`app/testperson.py`): fuera de reportes, estadísticas, ruleta y contadores; única excepción a la puerta de «creado» (y no en eventos finalizados).
- **Formulario de persona (Plan 4)** encendido también en producción (`PERSON_FORM_ENABLED=1` en `deploy/gcp/deploy.sh`). Cada evento lo activa aparte en su diseño: sin activarlo, nada cambia.

## Seguridad (cierre)
- 0C: 0 críticos y 0 altos abiertos (`0C_cierre.md`); lote 2 en producción desde el 3-nov.
- 1A: dos revisiones con correcciones (ver `15_MIGRACION.md`).
- 1B y trabajo del 5-nov, revisión dirigida (5-nov): enlace de correo de reimpresión (token de 256 bits solo como SHA-256, GET solo muestra, POST decide con UPDATE atómico de un solo uso, límite por IP, mensaje único para enlace desconocido/usado/vencido, `no-store`/`noindex`, `Referrer-Policy: no-referrer`) — sin hallazgos. Enlaces públicos de estadísticas (token SHA-256, vigencia máxima, revocables, solo agregados, límite por IP, `no-store`) — sin hallazgos. Persona «PRUEBA»: hallazgo propio corregido (la excepción de la puerta valía también para eventos finalizados; ahora solo en «creado», con prueba).
- Pendientes de seguridad que NO bloquean (con dueño): CSP completa y revisión de `X-Content-Type-Options` en una ruta estática (Fase 3); `ENFORCE_STAFF_TENANT` a 1 con dos clientes antes del SaaS; límites por IP en memoria por proceso (documentado; Neon/Redis si se escala).

## Orden del repositorio
- Ramas: GitHub tiene 68; 18 están totalmente fusionadas y listas para borrar (lista y SHA en `0B_ramas_borradas.md`, sección «5-nov»; las borra Juan David, la sesión no tiene permiso de escritura sobre ramas). Las que tienen commits propios sin fusionar se conservan.
- Documentación al día: este archivo, tablero del plan maestro (`29_PLAN_MAESTRO…` §18), `15_MIGRACION.md`, `HANDOFF.md`, `INDEX.md`, `CLAUDE.md`.

## Lo que queda abierto fuera de las fases (decisiones de Juan David)
Frecuencia del respaldo horario de Neon, apagar la VM antigua, cifras de Bogotá/Girardot del formulario del evento 11, lectura del cobro de Neon del 6-nov.

## Para la Fase 2
Leer `HANDOFF.md`, `ux/ESTANDARES_VISUALES.md`, `ux/PENDIENTES_VISUALES.md` y `15_MIGRACION.md`. Preguntas al iniciar: los «3 botones» por rol (digitador, coordinador, comercial) y qué quiere ver cada rol en el calendario.
