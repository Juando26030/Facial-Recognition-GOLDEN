# Fase 0A · Tarea 4 — Pendientes abiertos de `docs/15_MIGRACION.md` y `docs/16_BACKLOG_PRODUCTO.md`

Fecha: 2026-10-29. Solo lectura de documentos del repo (`origin/main` = `bc4a19d`); **no se accedió a la nube**. Todo lo que dependa del estado real de Cloud Run, Neon, Scheduler,
buckets, Secret Manager, Firebase o Cloudflare está marcado **«no verificado (nube)»**.

## Advertencias sobre las fuentes

- **Los dos documentos están desactualizados en sus marcas.** `docs/15` es una bitácora cronológica, no una lista de tareas: su única casilla `[ ] 3. Staging en Cloud Run` (línea 66) describe un
  estado de septiembre que ya pasó (staging se desplegó el 29-sep, sección «Staging desplegado»), y `docs/16` sigue marcando como `☐` cosas que ya están en `main` (B1, B1b, N4, 7a, R1 de B8).
  Por eso cada fila de abajo dice qué dice el documento **y** qué muestra el código (ver también `0A_estado_41_puntos.md`).
- Estado de producción tomado del plan maestro (§1): corre `b36bf92`, migraciones hasta `0075`, modo sin conexión encendido. No pude comprobarlo.

## A. `docs/15_MIGRACION.md`

| # | Pendiente (ubicación) | Qué dice el documento | Estado hoy | Quién |
|---|---|---|---|---|
| 15-1 | **Migración `0076` y los 6 commits de impresión del 29-oct no están en producción** (línea 850: «la recibe en el próximo despliegue autorizado») | Producción llega hasta `0075_transfer_jobs` | **ABIERTO.** `main` = `bc4a19d` ya los contiene; producción corre `b36bf92` (según el plan). Falta el despliegue con la receta de siempre (copia de Neon, PR con «Create a merge commit» + `[skip ci]`, orden «DESPLIEGA PRODUCCIÓN»). | Juan David |
| 15-2 | **Neutralizar la VM antigua** (D2.5, líneas 620–643): quitar `push` de `deploy.yml`, «Disable workflow» en Actions, detener el runner de la VM | «Tres cinturones, todos antes de fusionar» | **No verificado (nube/GitHub).** El plan 0B dice que `deploy/`, Gunicorn, Nginx y `deploy.yml` se marcan como heredados hasta que Juan David confirme que la VM está cerrada: **pregunta abierta de la Fase 0B**. | Juan David |
| 15-3 | **Renombre de la rama de staging** (`migra/fase1-2` → `staging`, paso aparte después del corte, líneas 625–631) | «Paso aparte, DESPUÉS del corte» | **ABIERTO** (`migra/fase1-2` sigue existiendo en `origin`, ver `git branch -r`). Tocaría `cloudrun.yml` y `bootstrap.sh staging`. | Juan David + Claude |
| 15-4 | **Lista de la «Sesión 3»** (líneas 788–793): `[~] 2. XFF_CLIENT_INDEX`, `[~] 3. Prueba de carga y simulacros 1 y 2`, `[ ] 5. Revisión final de pruebas y ruff` | Marcadas a medias o sin hacer | **Marcas viejas.** El hallazgo de la IP real se corrigió el 29-sep («D2.2 · Hallazgo… opción D, implementada») y las corridas de carga 1–10 están documentadas (D2.3). Lo que sigue **no verificado (nube)**: confirmar `XFF_CLIENT_INDEX` con tráfico real en producción y los simulacros 1 y 2. Revisión final de ruff: el CI hoy solo revisa archivos tocados (el plan 0B lo cambia a todo el repo). | Juan David / 0B |
| 15-5 | **Tabla de costos por componente** (líneas 728 y 792) | «Pendiente (no se pidió en esta sesión)» | **ABIERTO**, sin dueño ni fecha. | por definir |
| 15-6 | **DECISIÓN PENDIENTE: `jobs.kick()` y la CPU de Cloud Run** (línea 487 y «Decisiones pendientes tras la corrida 7», punto 2) | Agrupar `kick()` o `--no-cpu-throttling` en el servicio público | **ABIERTO como decisión.** No pude saber qué se desplegó en producción (nube). | Juan David |
| 15-7 | **Decisiones tras la corrida 7** (líneas 545–551): `FORM_LOCK_TIMEOUT_MS` 3000→~1500 (punto 3); función SQL única en autocommit y servicio aparte para `state` (punto 4); aviso a quienes se quedan sin cupo tardan 40–70 s (punto 5) | «Nada de esto está implementado»; el punto 1 (tope por conteo) ya está DECIDIDO | **ABIERTO** (3, 4 y 5). Afectan formularios masivos, no el piloto. | por definir |
| 15-8 | **Respaldos, D2.5j** (líneas 709–722): (b) restore-test con un respaldo real (solo se restauró uno de 17 KB contra el emulador); (c) alerta de borrado masivo y restauración de prueba de un objeto; (d) copia fuera de línea de `FACE_ENCRYPTION_KEY` | «Faltan…» | **ABIERTO.** Son los puntos 33–38 de la lista; la activación real de las copias de las 3 a. m. y la tarea `golden-ops-hourly` en producción: **no verificado (nube)**. | Juan David |
| 15-9 | **Ventana de historia de Neon en 1 día** y ciclo de vida de 30 días del bucket de staging (`HANDOFF.md` §6 paso 1; D2.5j) | «Paso manual» | **No verificado (nube).** | Juan David |
| 15-10 | **Mover staging de us-east1 a us-east4** (línea 730 en adelante; `deploy/gcp/move_region.sh`) | «Staging se traslada…; producción nace en us-east4» | **No verificado (nube).** La limpieza de la región vieja pide escribir la región; sin dueño ni fecha. | Juan David |
| 15-11 | **URL limpia para inscripciones** (D2.5k, línea 726) | «NO implementado» | **ABIERTO** (punto 32). `public_slug` no existe en el código. | Fase 7 |
| 15-12 | **Lista de verificación manual del quiosco** (línea 531: HTTPS, roster, service worker, cortar la red 20 s, recarga sin red…) y **preparación de dispositivos** (línea 532: abrir con red al llegar; iPad «Añadir a pantalla de inicio») | Casillas `☐` por evento | **ABIERTO por evento**, no una tarea única. Relevante: la recarga sin red sigue siendo la lenta (punto 27: `fix/offline-recarga` sin integrar). | Juan David (cada evento) |
| 15-13 | **Limpieza del «mundo VM»** (línea 163): copias `gs://<bucket-datos>/data/` con fotos y volcados viejos | «Pendiente del mundo VM (limpiar después del cambio)» | **No verificado (nube)**; ligado a 15-2. | Juan David |
| 15-14 | **Fase 3 (contingencia) → dispositivos reales**: Chrome Offline, modo avión, iPad Safari **como PWA instalada** (`docs/16` B8, «Dispositivos reales: pendiente») | Pendiente | **ABIERTO**: no hay constancia en el repo de pruebas en dispositivos reales. | Juan David |

## B. `docs/16_BACKLOG_PRODUCTO.md`

| Pieza | Marca del documento | Lo que muestra el código en `main` | Abierto |
|---|---|---|---|
| B1 Impresión USB desde el celular | ◐ prototipo, «falta la primera prueba con la impresora real» | Integrado en `shared-print.js`; la QL-800 se confirmó en hardware (memoria del proyecto), con el giro horizontal y los textos de `739da4e` aún por confirmar | Giro horizontal y textos (prueba física) |
| B1b iPad vía Android | ☐ | La ruta compartida lo cubre; sin prueba en iPad real | Prueba en iPad real |
| B2 Cédula en el alta de temporales | ☐ | Lectura solo para asistentes | **Sí** (Fase 4) |
| B3 / B3a / B3b Autorregistro por enlace | ☐ | No existe | **Sí** (Fase 4) |
| B4 Compromiso digital 30 días | ☐ | No existe | **Sí** (Fase 4) |
| B5 Base de digitadores y clientes | ☐ | No existe | **Sí** (Fase 4) |
| B6 Servidor local con sincronización | ☐ diseño en `docs/17` | No existe | **Sí** (Fase 6; preguntas abiertas de `docs/17`) |
| B7 Copias a las 3 a. m. | ☑ código · ☐ activarlo en producción | Código en `main` | Activación: no verificado (nube) |
| B8 Bandeja de salida | ☐ diseño; el estado del 5-oct dice R1 construida en `producto/piloto` | **R1 en `main`** (`outbox.js`, `outbox/sync`). R2–R5 no existen | **Sí** R2, R3, R4, R5; pruebas en dispositivos reales; texto 5-bis (revisión legal) |
| N1 Ficha configurable + estados + historial | ☐ esperando listas | Estados: solo API (sin pantalla); ficha e historial: nada | **Sí** (Fase 5; listas de Juan David) |
| N1b Calendario | ☐ esperando datos | Calendario básico existe | **Sí** (Fase 2/5) |
| N1c Registro touch | ☐ | Existe una primera versión | Confirmar alcance |
| N2 Correo al editar el evento | ☐ esperando lista de campos | No existe | **Sí** (Fase 5) |
| N3 Informe con encuesta | ☐ | Informe existe; sin encuesta ni bandera | **Sí** (Fase 7) |
| N4 Compartir impresora entre equipos | ☐ | Hecho (impresión compartida) | No |
| N5 Inventario inteligente | ☐ | Inventario de entregas por evento; sin catálogo por cantidad ni reglas de reserva | **Sí** (Fase 5) |
| N6 URL limpia | Después del piloto | No existe | **Sí** (Fase 7) |
| 7a «Acreditar» en todas las filas + Deshacer | «Aprobados… AL FINAL de la cola» | Hecho (`acreditarFila`, `undo`) | No |
| 7b Logo por defecto editable | «Aprobado… AL FINAL de la cola» | No existe | **Sí** (Fase 7) |
| «Qué falta para ESE evento» (9 puntos, §«Orden para el PRIMER EVENTO PILOTO») | Lista previa al piloto | El piloto ya se hizo (30-oct según el plan) | Cerrado salvo el punto 6 (criterio escrito de cuándo pasar al software de respaldo): **no hay constancia en el repo** |
| Decisión de J sobre datos en claro y TTL de la bandeja (7 días) | «Plazos decididos por J: 7 días» | Implementado en R1 | Cerrada |

## C. Dudas

- ¿La VM antigua ya se puede dar por cerrada (afecta 15-2, 15-13 y el borrado de `deploy/` en la Fase 0B)?
- ¿Quién es el dueño de 15-5 (tabla de costos) y 15-7 (decisiones de formularios masivos)? Hoy no tienen dueño ni fecha.
- Estado real en la nube de 15-4, 15-8, 15-9, 15-10 y 15-13: solo Juan David puede comprobarlo.
