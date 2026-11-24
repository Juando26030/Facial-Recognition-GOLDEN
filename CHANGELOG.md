# Registro de cambios — GoldenWeb 2.0

Qué cambió, cuándo y para quién, en orden del más reciente al más viejo. Formato libre inspirado en «Keep a Changelog»: una sección por
despliegue o por bloque entregado, con la migración de Alembic que trae y el documento donde está el detalle. **Este archivo se escribe al
cerrar cada pieza** (ver `CONTRIBUTING.md` § Definición de «hecho»). Lo anterior al 1-nov-2026 está en `docs/historial.md` y en los cierres
de fase (`docs/CIERRE_*.md`); este archivo arranca en noviembre de 2026 y se armó el 22-nov-2026 a partir de `docs/historial.md`,
`docs/ESTADO_2026-11-11.md`, `docs/FASE_10_AJUSTES_NOV10.md`, `docs/25_INVENTARIO_POR_BASE.md`, `docs/23_EVENTO_COMPARTIDO_NUBE.md` y el historial de git.

Estados: **Producción** = corre en `app.golden-eventos.com` · **Staging** = probado en staging, pendiente de autorización · **Rama** = construido, sin probar con base.

## 2026-11-23 (noche) — Confirmaciones con palabra y coordinador del evento nuevo (Rama; sin migración)

- **Staging (24-nov):** sitio web republicado con el arreglo de tableta (`39e4c6f`); pruebas E2E contra staging: 12 pasan, 6 se saltan por falta de datos o impresora. Informe de la segunda pasada: `docs/revision_2026-11-22b/README.md`.

- **Pruebas E2E:** `tests/e2e/conftest.py` anula los preparativos automáticos del `conftest.py` general (Postgres local, migraciones, dobles). Las E2E ya corren en cualquier máquina (p. ej. Cloud Shell) con solo `playwright` + `pytest`, sin base de datos local.
- **Pruebas E2E:** el evento sintético completa solo lo que exija la plantilla de staging (país, ciudad, horas, coordinador, comercial, categoría, campos personalizados…), leyendo `/api/event-template`; antes el servidor lo rechazaba (400) y 8 pruebas se saltaban.
- **Arreglo (pedido de Juan David):** en TODAS las pantallas que piden escribir una palabra para borrar o confirmar (REABRIR, ELIMINAR, SUPRIMIR, REVOCAR, REEMBOLSAR, DESHABILITAR, BORRAR, CARGAR, nombre del evento, nombre del campo), si la palabra está mal o vacía el cuadro ya NO se cierra en silencio (parecía que se había borrado y no): muestra ahí mismo el aviso rojo «No se hizo nada…» y deja corregir o cancelar. Se hizo en `showPrompt` (opción `validate`) y lo usan todos los llamadores.
- **Arreglo:** el desplegable «Coordinador» del evento nuevo ya no ofrece coordinadores temporales (ni archivados): usa la misma lista que valida el servidor. Antes el servidor respondía «El coordinador asignado no es válido». Archivos: `static/js/toast.js`, `static/js/gw-confirm-typed.js`, `app/event_template_svc.py`.
- **Cambio (decisión de Juan David):** el digitador ya no ve «Material de Golden» (los equipos y computadores que Golden alista para el evento): se quitó la tarjeta, se bloquea la página `/kiosk/{id}/alistamiento` y el API `inventory-checklist` pide coordinador o superior. «Control de inventario» (entregas a las personas) sigue igual para él.
- **Cambio (decisión de Juan David):** se quitó el botón «Guardar sin registrar» para TODOS (también el digitador). Corregir un dato sin registrar lo hace solo coordinador o superior, cambiando «Estado de registro» a «No registrado» y guardando. El digitador solo tiene «Guardar y registrar». Además, quien queda «No registrado» tras editarse ya no muestra «Recién registrado»: dice «Recién editado» (`static/js/directory.js`).

## 2026-11-23 — Registro y escáner facial: pruebas en staging de `saas/revision-integral` (Rama; sin migración)
- **Arreglo:** la cámara del escáner no encendía (`setOff` se usaba antes de definirse y detenía `app.js` al cargar). El mismo error está en `main` y en producción; hoy esa pantalla no se usa allí. Pendiente de subir con el paquete de producción.
- «Editar persona»: botón «Captar rostro» (mismo camino con aceptación de la persona); si ya hay foto de registro, se muestra y el botón pasa a «Retomar la foto» (`GET /api/events/{id}/users/{uid}/registration-photo`, digitador o más, `no-store`).
- Un solo botón por persona: una persona ya acreditada solo se avisa (recuadro verde), sin segundo botón ni pregunta (en línea; sin conexión sigue preguntando). Resultado del escáner en recuadro: verde = ya consta/acreditada, amarillo = no se logró detectar el rostro (repetir), rojo = no está en la base (`reason: no_face | no_match`).
- Panel de comparación del escáner (foto de registro y captura lado a lado): botón «Acreditar a esta persona» (acreditación con método biométrico), sin pasar por «Editar».
- Foto pendiente: al verificar a la persona NO se reemplaza la foto de registro; la selfie se conserva como segunda foto (`enroll.selfie_photo_key`, cubierta por toda purga/supresión) y «Editar» muestra las dos como historial. El reconocimiento sigue usando la foto de registro. Al aceptar desde el celular, si la selfie queda pendiente, el mensaje lo dice con claridad.
- Escáner sin escribir la cédula y anexo (cambio del 23-nov-2026): con modo facial y fotos del cliente, el modo «acepto» de un clic se enciende solo. En Parámetros › Reconocimiento facial aparece «Anexo firmado del cliente» (PDF, Word, Excel o imagen, 10 MB): sin el archivo la cámara queda bloqueada, con el motivo, en el servidor (`/recognize`, `/consent-click`) y en el registro. Sustituye al formulario de referencia/fecha/casilla del súper administrador (la API `precalculo-autorizado` sigue).
- Tercer origen de la foto «Cada quien acepta» (migración 0165, `events.each_accepts`): formulario, QR o enlace. En la puerta el escáner no pide cédula: sale «Acepto», se abre la cámara y solo se reconoce a quienes ya aceptaron (no se compara con quien no aceptó). No exige anexo. Los otros dos: «Golden se hace cargo» (cédula primero) y «el cliente entrega las fotos» (anexo obligatorio).
- Parámetros › Reconocimiento facial: un solo selector de tres modos (Golden se hace cargo / la empresa se hace cargo de las fotos / cada quien acepta) en vez de «responsable» + «origen de las fotos». Empresa y «cada quien» son evento de un tercero (piden los datos del organizador). El campo del anexo está siempre en la página y se muestra con el modo «empresa». La opción «Permitir imprimir la foto del rostro en la escarapela» pasa de súper administrador a cualquier coordinador.
- Escáner con «Acepto»: si el escaneo falla (no se detectó el rostro o no está en la lista) la cámara sigue abierta y se puede reintentar hasta 3 veces en 100 s sin volver a pulsar «Acepto». El «no está en la lista» dice con cuántos rostros listos se comparó (solo un número). Botón «Copiar enlace» en el cartel con QR de Invitaciones.
- Modo «Acepto» sin cédula: el escáner ya no abre la pantalla de autorización al entrar; muestra «Continuar: llegó una persona» y, al pulsarlo, la persona acepta y se abre la cámara (al terminar vuelve a «Continuar»). En «cada quien acepta» la comparación también incluye a quien aceptó desde el celular y aún no verificó su documento (antes quedaba fuera: «se comparó con 1 rostro»); su resultado es siempre «pendiente» y «Acreditar» exige confirmar el documento (verifica la aceptación) antes de acreditar.
- «Por verificar» eliminado (decisión de Juan David, 23-nov-2026; misma lógica de un formulario abierto): quien acepta (puerta, formulario, QR o enlace) queda aceptado y se reconoce de inmediato; la selfie reemplaza la foto de registro directamente; ya no hay foto «pendiente» ni el interruptor «Verificar antes de reemplazar la foto» en Parámetros (la columna `accept_verify_photo` queda sin efecto). Las aceptaciones de `web_acceptances` se registran como verificadas («link» o «auto»). Esto deshace el hallazgo 5 de la revisión de seguridad por decisión expresa del dueño: cualquiera que conozca la cédula (y la fecha de nacimiento, si la base la trae) puede dejar su selfie bajo esa persona.
- Revisión de la Fase 5 (`docs/revision_2026-11-22b/03` a `05`): foto nueva borra la pendiente, catálogo CRM y revocar servidor cerrados a cuentas de otra empresa, `autodestruir.ps1` con candado, 204 de cotización sin cuerpo.

## 2026-11-23 — Hotfix: estadísticas por estado de registro (rama `hotfix/estadisticas-registro-2026-11-23` sobre `main`; también en `saas/revision-integral`) — sin migración
- Parámetros › Campos: al activar «Estadística» se elige sobre quién se cuenta (toda la base / solo registrados / solo no registrados); viaja en `default_chart_type` como `<gráfico>@<alcance>`.
- Estadísticas: selector por gráfica para cambiarlo solo por el momento (al recargar manda lo de Campos); también en el enlace de solo lectura. Zonas, inventario y dependientes no lo llevan.
- Barras de categorías de un color por categoría (panel y Excel). Excel: hojas «Gráficos registrados» y «Gráficos no registrados».

## Sin publicar (rama `saas/revision-integral`, 22-nov-2026)
- Revisión integral del repositorio por roles (`docs/revision_2026-11-22/`); documento consolidado de reglas inamovibles (`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`).
- `CHANGELOG.md`, `CONTRIBUTING.md`, plantilla de PR y README raíz al día (esta revisión).
- 22-nov (segunda tanda, decisiones de Juan David): `/instalar` retirado; plazo de gracia del servidor local conectado (`LOCAL_GRACE_DAYS`); al deshabilitar una llave el servidor se da de baja solo (`deploy/windows/autodestruir.ps1`, apagable con `LOCAL_WIPE_ON_DISABLE=0`; deshabilitar pide escribir la palabra); `deploy/windows/proteger-disco.ps1` (BitLocker gratuito, solo si Windows lo trae); sitio: fuente libre Poppins, contacto de la plataforma y cotización con envío real (`POST /api/public/quote-request`, variables `QUOTE_TO_EMAIL` y `QUOTE_ALLOWED_ORIGINS`); `docs/PROPUESTA_FINANCIERA_SAAS_2026-11-22.md`.
- 22-nov: `main` puesto al día con la línea de producción (fusión de `prod/llaves-escaner-2026-11-20`, `hotfix/subida-formulario-2026-11-21` y `feat/evento-compartido-nube`; sin conflictos; árbol idéntico a `feat/evento-compartido-nube`).

## 2026-11-22 — Registro: lo elegido se ve completo en cualquier ancho (Staging, rama `feat/inventario-base`)
- Cédula, nombres y apellidos siempre visibles; «Mostrar en el registro» elige los demás campos, cada uno como columna con su nombre;
  nada termina en «…» (la fila crece); con poco ancho la persona pasa a dos renglones. Barrido de 320 a 3440 px en 25 pantallas sin desplazamiento horizontal.
- Dependientes: una fila es «la misma» por titular + dependiente + producto/cantidad; corregir otros datos o reordenar el archivo no duplica lo entregado.
- Detalle: `docs/25_INVENTARIO_POR_BASE.md` §11-12.

## 2026-11-21 — Inventario «lo define la base», dependientes y candados (Staging) — migración `0161_inventario_por_base`
- Lo que le toca a cada persona se calcula en vivo desde la base cargada (`app/inv_assign.py`); entregas solo a registrados, nunca dos veces; por línea o todo.
- Base de dependientes (virtual, solo en Parámetros / Editar persona / Estadísticas); vista previa obligatoria antes de cualquier carga (`app/roster_preview.py`).
- Bloqueo por evento con contraseña del digitador (registro, zonas, inventario; 5 intentos → 5 min) en `app/config_lock.py`.
- Tipo de campo «Número», «Mostrar en el registro» por campo, «Aplicar a todos los campos de texto» en el diseñador del formulario de persona.
- Detalle: `docs/25_INVENTARIO_POR_BASE.md`.

## 2026-11-21 — Hotfix: subida de archivos del formulario público en celulares (Producción, `hotfix/subida-formulario-2026-11-21`)
- «Error de red al subir el archivo»: `direct-upload.js` copia el archivo a memoria al elegirlo y reintenta con una URL nueva si la conexión se corta. Huella de `tests/test_publico_congelado.py` renovada por orden expresa.

## 2026-11-21 — Evento compartido entre servidores locales con la nube como puente (Producción, commit `4615fb4`) — migración `0160_shared_local_events`
- Varios servidores locales atienden el mismo evento; antes de entregar o dejar entrar consultan a la nube; sin internet la acción sigue con aviso.
- Copia completa del evento en la nube (`app/local_backup.py`) como seguro contra la pérdida del servidor. Paquete de actualización de servidores locales `2026.11.21.222212`.
- Detalle: `docs/23_EVENTO_COMPARTIDO_NUBE.md`.

## 2026-11-20 — Llaves de producto del servidor local y cierre por inactividad (Producción, `prod/llaves-escaner-2026-11-20`) — migraciones `0158_local_server_keys`, `0159_node_disabled_at`
- Llaves de producto: crear, ver, deshabilitar; instalador liviano; el servidor local se bloquea al deshabilitar la llave (`app/server_keys.py`, `app/server_lock.py`).
- Cierre de sesión por inactividad ajustado a pedido de Juan David (`docs/22_SESION_INACTIVIDAD.md`).
- Detalle: `docs/17_SERVIDOR_LOCAL.md` § Llaves de producto.

## 2026-11-19 — Lector de cédula por cámara y prueba de carga «rush» (Producción, `prod/lector-2026-11-19`)
- Página de prueba `/pruebas/lector-cedula` (PDF417 con `zxing-wasm`), pestaña «Cédula nueva» y Registro → «Escanear» con tres modos (cédula vieja · cédula nueva · QR), recordando el último.
- Prueba de carga «rush» autorizada en producción sobre un evento sintético, con candados en `deploy/loadtest/run_phase4.sh` (`docs/PRUEBA_CARGA_PRODUCCION.md`).
- Escarapela digital con la misma plantilla que la física y el código de la persona (`docs/ESCARAPELA_DIGITAL_DATOS.md`).

## 2026-11-18 — Almacén piezas 3 y 4, preimpresión por categoría, diseñador emergente y guardado unificado (Producción, `prod/integrado-2026-11-18`) — migraciones `0150`–`0157`
- Almacén: novedades y bloqueo (`0152_almacen_novedades`), Excel del checklist, serial y archivos por unidad (`0155_almacen_serial_y_archivos`).
- Preimpresión con estado por categoría (`0150_print_logs_kind`, `0151_merge_preimpresion`); solo se imprime a quien ya está registrado, salvo preimpresión y certificados; sin hojas en blanco.
- Diseñador de escarapelas emergente y compacto en celular; guardado unificado y estilo común en las pantallas (`docs/ux/GUARDADO_UNIFICADO.md`); menú ocultable.
- CRM implica inventario y categorías (`0153`, `0154`); orden de legalizaciones (`0156_legalizacion_orden`); sincronización de impresiones (`0157_sync_prints_changes`).
- Correo de contacto legal pasa a `soporteit@goldenlogisticas.com` en pie legal, términos y reembolsos.
- Detalle: `docs/ALMACEN.md`.

## 2026-11-17 — Almacén piezas 1 y 2, gráfico de gastos y UX por pantalla (Staging) — migraciones `0148_almacen_unidades`, `0149_almacen_movimientos`
- Catálogo con controles, unidades con serial, QR y etiquetas; salidas y entradas por QR, alistado por fila, tablero del evento y foto del elemento.
- Panel de gastos: gráfico de barras; Neon pide el rango que cubre el mes completo.
- Ronda visual por pantalla (ramas `ux/base`, `ux/kiosk`, `ux/evento`, `ux/admin`, `ux/crm`, `ux/inventario`, `ux/almacen`).

## 2026-11-16 — CRM, coordinador temporal y contactos del cliente (Producción, commit `1d5ed06`) — migraciones `0130`–`0146`
- CRM completo (cuentas, contactos, oportunidades, cotizaciones con diseñador de PDF, plantillas, productos, importación de SuiteCRM). Apagado en producción (`CRM_ENABLED=0`).
- Coordinador temporal (`staff_users.event_only`): solo sus eventos; lista de rutas permitidas en `app/event_only.py` (`0146_event_only_staff`, `docs/COORDINADOR_TEMPORAL.md`).
- Eventos: duplicar, borrar la base cargada, código sugerido, contactos del cliente por evento (`0145_event_contacts`); informe final y encuesta automática al contacto principal al pasar a «Facturado».
- Código de la persona y subcategorías (`0140_codigo_subcategorias`, 12-nov; campo desde el 17-nov): serial aparte de la cédula, solo con el interruptor del evento.
- Legalizaciones: modelo de datos (14-nov) y formato Excel (`0147_legalizaciones_formato`, 17-nov).
- Detalle: `docs/PASO_A_PRODUCCION_2026-11-16.md`, `docs/crm/README.md`.

## 2026-11-11 — Fases 5 a 9 + ajustes (Producción, commit `0899e02`) — migraciones hasta `0129_staff_client_temp`
- Cliente temporal (`cli-xxxxxx`, contraseña mostrada una vez), listas por ancho de contenedor, «(opcional)» en negrilla en formularios públicos,
  descarga ZIP de archivos de formularios, paso a «tiempo real» que encola inscripciones existentes.
- Fase 10 (10-nov): «Mostrar con asteriscos» por campo, prellenado del compromiso, Acta de novedades, historial de cambios por persona,
  descarga del instalador local, cuentas de cobro abiertas y gastos de infraestructura, inventario/control de áreas/autoescaneo, QR en vCard, ruleta y calendario;
  Job horario económico (Neon puede dormir).
- Fases 5-9 (9-nov, `f5/integracion`): eventos configurables (facturado, encuesta, jornada, historial, inventario), servidor local Windows con instalador, URL limpia de inscripciones,
  QR dinámico/Wallet, contactos de expositores, cobros Wompi multicuenta, alertas de borrado masivo y copia semanal cifrada a OneDrive.
- Detalle: `docs/ESTADO_2026-11-11.md`, `docs/FASE_10_AJUSTES_NOV10.md`, `docs/REVISION_F5-9_PLAN_VS_CODIGO.md`, `docs/FASE_9_PLATAFORMA.md`.

## 2026-11-09 — Fase 4: Equipo del evento (Producción, commit `2c8c4d7`) — migraciones hasta `0104`
- Compromiso digital del digitador con firma, credenciales por correo, autorizar a todos, clave de primera vez, descargas de bases solo para administradores.
- Detalle: `docs/CIERRE_FASE_4.md` y `docs/FASE_4_*.md`.

## 2026-11-07 — Fase 2 (diseño y calendario) y Fase 3 (CRUD, archivado, seguridad) (Staging, `f2/integracion`) — migraciones `0087`–`0094`
- Plantillas de evento, calendario, archivado y auditoría de personas/staff/eventos/catálogos; matriz CRUD y ronda de seguridad.
- Detalle: `docs/CIERRE_FASE_2.md`, `docs/FASE_3_AUDITORIA.md`, `docs/FASE_3_SEGURIDAD.md`.

## 2026-11-05 — Cierre de las Fases 0 y 1 (Producción, despliegue del 5-nov 9 pm)
- Fase 1A: buscador único (cédula, nombre, empresa, lector), cola compartida de impresión, carga flexible, autoimpresión, formulario de persona, parámetros agrupados, permisos del coordinador.
- Fase 1B: reimpresión con permisos de un solo uso aprobados por el coordinador del evento (pantalla o correo). Persona de prueba `PRUEBA` en cada evento.
- Fase 0B/0C: limpieza del repositorio (72 ramas borradas, `docs/0B_ramas_borradas.md`), `ruff` en todo el repo, escáneres de seguridad, hallazgos corregidos.
- Detalle: `docs/CIERRE_FASES_0_1.md`, `docs/1B_reimpresion_permisos.md`, `docs/historial.md` (entradas del 1 al 5 de noviembre).

## 2026-11-01 a 04 — Formularios web y eventos en curso (Producción con el cierre del 5-nov)
- Formularios: valores de la base como opciones (P7), texto con formato (P3), ancho configurable (P4), paso de identificación editable (P5), nombre de presentación (P8),
  condiciones en árbol y variantes (P9), editor plegable (P10), tabla de variantes (P11/P11b), hojas (P12). Mensaje editable de cupo lleno; cupo en 0 = cerrado temporalmente.
- Eventos en curso: «Solo agregar personas nuevas» (`app/roster_append.py`) y devolver un evento «en curso» a «creado».
- Contraseñas con motivo claro y «ojito» en el inicio de sesión.
- Detalle: `docs/historial.md` (secciones del 1 al 4 de noviembre).
