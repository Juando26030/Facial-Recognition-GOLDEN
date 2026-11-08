# Cierre de la Fase 2 (plantilla de evento y calendario) — 7-nov-2026

Documento para Juan David. Resume qué se entregó en la Fase 2, qué decidió él, qué se probó, qué queda pendiente y cómo se pasará a producción cuando él lo autorice. **Este documento no ejecuta nada en producción.**

- **Rama de la Fase 2:** `f2/integracion` (en GitHub, `origin/f2/integracion`). Último cambio de la Fase 2: `a34b6bc`, «Pulido visual: botones de la cuenta en una fila y tarjetas angostas del calendario (laptop 1366 px)». Después se fusionaron sobre ella piezas de la Fase 3 (ver `FASE_3_AUDITORIA.md`); el SHA exacto de lo que se lleve a producción lo fija Juan David en su autorización.
- **Estado:** vive solo en staging. **Producción NO tiene nada de esto** (sigue en `main`).
- **Alcance acordado:** `FASE_2_ALCANCE.md` (decisiones del 7-nov-2026) y el plan maestro `29_PLAN_MAESTRO_ETAPA_2026-10-29.md`.

## 1. Qué se entregó

### Plantilla de evento (migración `0087_event_templates`)
- Una **plantilla única** que gobierna dos pantallas: qué pide «Nuevo evento» y qué sale en la tarjeta del calendario. Se diseña en Configuración → «Plantilla de eventos» (solo super_admin y admin), con el estilo del editor de formularios web: arrastrar, mover y cambiar parámetros.
- **Tipos de campo:** texto corto y largo, lista desplegable (el admin define las opciones), dinero, número, comercial, coordinador, fecha, hora y fecha-hora con título propio, país, ciudad, dirección con mapa, contacto, colores de pañoleta e inventario.
- **Campos base** (código, nombre y cliente): siempre obligatorios y no se pueden quitar. El resto lo decide el admin.
- **Los interruptores de «Nuevo evento» y de «Parámetros del evento» son lo mismo:** una sola fuente de datos, dos pantallas.
- **Seguridad del cambio:** si dos administradores editan a la vez, el segundo recibe un aviso claro y no pisa al primero. Se guardan las últimas 50 versiones de la plantilla. Retirar un campo conserva sus datos; nunca se borra información.
- **Editar evento** muestra y guarda los campos de la plantilla («Información adicional del evento»).
- **Crear evento desde «Eventos»** además de desde «Clientes»: pide elegir el cliente en una lista con buscador. Desde un cliente, ya viene asignado.
- **Diseñador:** espaciado ordenado; el nombre y el tipo del campo salen en líneas separadas.

### Países, ciudades, mapa e inventario
- **País y ciudad:** lista fija dentro de la plataforma (202 países; Colombia con más de 300 municipios), con búsqueda escribiendo y sin servicios externos. Si la ciudad no está en la lista, se escribe libre.
- **Dirección con mapa:** gratis (OpenStreetMap con búsqueda de direcciones). Google Maps queda para más adelante si hace falta.
- **Inventario:** el administrador define tipos y referencias; al crear o editar el evento se piden cantidades («dos computadores, tres impresoras…»). Todavía no se conecta con el módulo de inventario del quiosco (Fase 5).

### Calendario
- Lo ven super_admin, admin, comercial y coordinador (no digitador ni cliente).
- **Tarjeta completa o plegada:** el botón «Plegar/Desplegar eventos» alterna entre la tarjeta con toda la información de la plantilla y una versión corta (línea de color, nombre completo y código). Por defecto va desplegada. Siempre cuadrícula de 7 columnas; en pantallas angostas pasa a lista por días. Misma tarjeta en Mes, Semana y Día. Pulido para laptop de 1366 px.
- **Filtros:** por comercial, por coordinador y por estado del evento.
- **Interruptores como píldora** (ícono + nombre, «Sí/No»).
- Al tocar un evento se abre un cuadrito con las mismas acciones de la fila de Eventos/Clientes (Ingresar, Editar, Cambiar estado, Exportar, Eliminar), con los mismos permisos de siempre.

### Otros ajustes
- **«Impresión compartida y por USB» pasó a llamarse «Impresión compartida».** No se tocaron los parámetros inamovibles de impresión (Brother QL-800).
- **Botón «Ingresar» dorado** en Eventos, Clientes y calendario.
- **Apellido en «Registrar nuevo»:** se detecta solo al cargar la base; si la base trae nombre y apellido juntos, el apellido no es obligatorio.
- **Botones de la cuenta** en una fila.

### Cambios de la Fase 3 que viajan junto con la Fase 2
Archivar y restaurar (clientes, usuarios del personal, eventos, personas, formularios, áreas, inventario, colores y plantillas de escarapela), borrado definitivo solo super_admin, registro de acciones (`audit_actions`), L7 corregido (a los 90 días se archiva **solo la base de datos del evento**, una vez por semana) y modo tranquilo del Job horario. Migraciones `0088` a `0092`. Detalle y estado en `FASE_3_AUDITORIA.md`.

## 2. Decisiones de Juan David (7-nov-2026)
1. Lo visual ya hecho en la Fase 1 no se toca; lo nuevo usa los mismos estándares (`ux/ESTANDARES_VISUALES.md`).
2. Calendario visible para super_admin, admin, comercial y coordinador. Clic en un evento = cuadrito de acciones.
3. Países y ciudades: lista fija dentro de la plataforma, sin servicios externos.
4. Mapa gratis (OpenStreetMap).
5. **Los eventos existentes NO se migran todavía.** Primero se construye la plantilla; cuando se entienda qué va en cada campo, se migran.
6. Páginas públicas: siguen congeladas.
7. Archivar = ocultar sin borrar y se puede restaurar. L7 (aprobado por la auditora): a los 90 días solo se archiva la base de datos del evento, una vez por semana; la biometría sigue con su purga a los 7 días.
8. Staging apagado salvo cuando se prueba (`staging_power.sh`). Modo tranquilo del Job horario: sin actividad, la base descansa.
9. VM antigua: cerrar lo que no se use en Google Cloud; borrarla solo con instantánea final y revisión previa.
10. Producción solo con su autorización explícita para el SHA exacto.

## 3. Pruebas hechas
- **Staging:** despliegues 36 a 41 de la Fase 2 y de la Fase 3 (oleadas 1 a 5 y modo tranquilo), revisados por Juan David en `app` de staging.
- **Pruebas rápidas** (sin base de datos) y pruebas de pantalla (`tests/js`): pasaron en cada pieza.
- **Prueba completa con base de datos (~47 minutos, en Cloud Shell): AÚN NO se ha corrido después de la Fase 3.** Debe correrse sobre el SHA final antes de pedir permiso para producción. Comando: `python -m pytest -q` (crea su propia base `golden_test`). Las pruebas `tests/test_event_template.py`, `tests/test_enlace_fase2.py` y las de archivo quedaron por confirmar en esa corrida.
- Strix y ZAP contra staging: pendientes (ver Fase 3).

## 4. Pendientes heredados
| Pendiente | Detalle |
|---|---|
| `tests/test_fase_1_9_ajustes.py` falla | Falla desde antes de la Fase 2 por el asterisco naranja de los campos obligatorios. No es de esta fase; hay que actualizar la prueba o el color. |
| Leaflet sin SRI | La librería del mapa se carga sin la huella de integridad (SRI). Falta ponerle versión fija y huella, o alojarla dentro de la plataforma. |
| Lista de ciudades fuera de Colombia | Elaborada a mano; revisar y ampliar (`scripts/geo_fuente/`). |
| Migrar eventos existentes a la plantilla | No se hizo, por decisión de Juan David. Todo funciona sin ello. |
| Rama `docs/cierre-fase-1` sin llegar a `main` | Tiene documentos de cierre de la Fase 1; `FASE_2_ALCANCE.md` y este documento pueden chocar al fusionar (add/add). Quedarse con el de la rama que traiga más y agregar la sección faltante. |
| GitHub Actions bloqueado por facturación | Por eso se despliega con `deploy/gcp/manual_deploy.sh` desde Cloud Shell. |
| Ruleta como interruptor de la plantilla | Falta primero un interruptor en Parámetros. |
| Inventario ↔ módulo operativo del quiosco | Fase 5. |

## 5. Cómo se pasaría a producción (NO ejecutar sin autorización)
Solo Juan David da la orden y la corre; Claude no ejecuta nada en la nube.

1. **Autorización explícita de Juan David para ESE SHA** (se escribe el SHA completo; si cambia un solo commit, se pide de nuevo).
2. **Prueba completa con base de datos en Cloud Shell, verde** sobre ese SHA, y revisión final en staging.
3. **Copia de seguridad de Neon primero** (rama o copia de la base de producción) y confirmar que el respaldo reciente existe en el bucket.
4. **Ningún evento en proceso** (el despliegue respeta el congelamiento; no usar `FORCE=1` para saltarlo salvo orden expresa).
5. **Sin `force`:** nada de `git push --force` ni de saltarse el congelamiento.
6. **Migraciones `0087` a `0092` y las que se sumen (`0093` en adelante) son aditivas** (tablas y columnas nuevas, nada se borra ni se cambia). Se verifican antes: cadena de Alembic de un solo extremo, ids de 32 caracteres o menos, aplicadas con la conexión directa del rol dueño.
7. Despliegue desde Cloud Shell con `deploy/gcp/manual_deploy.sh production <ID-del-proyecto>` (ver `19_GUIA_PRODUCCION.md` y `13_RUNBOOK_PRODUCCION.md`).
8. **Revisión posterior:** abrir `/health`, entrar, ver calendario y Nuevo evento, comprobar que el Job horario corre. Para volver atrás: `gcloud run services update-traffic <servicio> --to-revisions <revisión>=100 --region us-east4`.
9. Activar `ENFORCE_STAFF_TENANT` y las demás decisiones de la Fase 3 **aparte**, cada una con su permiso.
