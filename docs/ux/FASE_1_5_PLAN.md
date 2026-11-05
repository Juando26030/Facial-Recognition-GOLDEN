# Fase 1.5 · Rediseño visual de TODO el sitio — plan de ejecución

Pedido de Juan David (5-nov-2026): antes de la Fase 2, llevar **todas** las pantallas, pestañas y botones al diseño nuevo. Este documento es la receta: cuando se ejecute, solo hay que hacer lo que dice. Medición: 49 plantillas; solo 6 usan hoy el diseño nuevo (`gw-page`): `kiosk_registro`, `kiosk_roster`, `kiosk_parametros`, `login`, `form_stats` y la base `_gw_head`. Mide el trabajo real: ~40 pantallas, ~690 estilos en línea (268 solo en el editor de formularios) y ~540 colores sueltos.

**Decisiones de Juan David (5-nov-2026, 15:53):** (1) el orden de olas está aprobado; (2) Ctrl/⌘+S **y** el botón Guardar, con el aviso «Hay cambios sin guardar», en TODAS las pantallas que editan datos; (3) **lo que ven las personas (formulario público, consentimiento, escarapela digital, certificado, páginas legales, pantalla del proyector) NO se rediseña por ahora y queda EXACTAMENTE igual** — hay un formulario activo; el rediseño es solo del lado administrador/diseñador (incluida la configuración del formulario); (4) **a staging se manda por piezas, a producción TODO en una sola entrega**.

**Lo que NO se toca (reglas inamovibles):** los parámetros de impresión (`IMPRESION_PARAMETROS_INAMOVIBLES.md`; `badge_print.html` queda fuera por completo), los textos legales de la auditora (en las páginas legales solo cambia el marco visual, nunca una palabra), y la lógica de negocio (mismos ids, rutas, permisos y respuestas de la API). Es un cambio de piel y de orden de pantalla, no de funciones; ninguna función se esconde ni se elimina.

## 0. Congelado: lo que ven las personas (no se toca en toda la Fase 1.5)
Archivos congelados (ningún PR de la Fase 1.5 los modifica): `templates/form_public.html`, `aceptar.html`, `aceptar_no_disponible.html`, `digital_badge.html`, `certificate_public.html`, `legal_*.html`, `roulette_display.html`, `badge_print.html`; y los scripts/estilos que cargan: `form-render.js`, `rich-text.js`, `direct-upload.js`, `fonts-propias.js/css`, `cookie-notice.js`, `badge-render.js`, `roulette-render.js`, `photo-capture.js`, `agrandir.css`. Esas páginas **no cargan** `design-system.css` ni `style.css`, así que lo global (modo touch, componentes) no las alcanza. Candado: `tests/test_publico_congelado.py` guarda la huella (SHA-256) de esos archivos y falla si cambia uno (para tocarlos hay que cambiar la huella a propósito, con orden de Juan); además compara el HTML de `/f/{evento}/{slug}` contra una copia de referencia. Cuidado especial: `form-render.js` también lo usa la vista previa del editor de formularios; el editor se rediseña alrededor, nunca ese script.

## 1. Reglas globales (valen para TODAS las pantallas)

**R1 · Un solo «Guardar» por pantalla, como en Parámetros** (botón **y** Ctrl/⌘+S, aviso «Hay cambios sin guardar» y aviso al salir). Barra pegajosa abajo (`.gw-savebar`) que acompaña siempre; dice «Hay cambios sin guardar» / «Guardado» / qué falló; un solo botón que guarda todo lo pendiente (motor `static/js/params-save.js`, `GWParams`). Se acabaron los «Guardar X», «Guardar Y» y el «Guardar general» al final. Cada bloque se registra con su `save()` y su clave. Si se intenta salir con cambios pendientes, avisa. Lo que NO es edición de datos no pasa por la barra y sigue inmediato con confirmación: crear/borrar/archivar/aprobar/enviar/descargar (ej. «Eliminar» siempre con `showConfirm`, en rojo). Pantallas sin datos que guardar (listas, estadísticas, impresión) no llevan barra.
**R2 · Rueda que gira en TODO botón que trabaja.** El estilo ya existe (`.gw-btn[aria-busy="true"]`, anillo girando). Se agrega un ayudante único `GW.busy(boton, promesa)` en `static/js/gw-ui.js`: pone `aria-busy`, bloquea doble clic, muestra la rueda, y al terminar muestra éxito o el error en la misma barra o aviso. Se usa en **todo** botón que dispara una petición (guardar, crear, subir, enviar, descargar, aprobar), no solo en Guardar. Si tarda más de ~8 s, el texto cambia a «Sigue trabajando…».
**R3 · Todo en secciones, igual que Parámetros.** Pantallas con varios temas usan pestañas (`.gw-tabs`, máx. 8, con resumen de una línea) y dentro de cada pestaña grupos desplegables (`.gw-group`, máx. 2 niveles; lo frecuente abierto, lo avanzado plegado). Pantallas de una sola cosa (login, aceptar) no llevan pestañas. Se recuerda la pestaña por dispositivo (como ya hace `params-save.js`).
**R4 · Guía, ayuda y recorrido en cada pantalla.** Cada pantalla trae: banda «Guía de 3 pasos», «?» (`.gw-help`) junto a cada concepto no obvio, y recorrido de primera vez (`.gw-tour`, `data-gw-tour` + `data-gw-tour-auto`, una vez por dispositivo y por pantalla, con «Ver recorrido de nuevo» en el «?» de la cabecera) con animaciones suaves (respetan `prefers-reduced-motion`). Los 3 pasos de cada pantalla están en la ficha (§5). Las páginas públicas están congeladas (§0).
**R5 · Celular y tableta automáticos en TODAS las pantallas.** Hoy el «modo touch» vive dentro de `shared-print.js` y solo aplica en Registro. Se mueve a una pieza global: `touch-detect.js` se carga desde `_gw_head.html` (todas las pantallas) y las reglas pasan a `design-system.css` bajo `body.touch-mode` y `@media (max-width: 768px)`. Reglas: objetivos táctiles ≥ 44 px (48 en acciones principales); sin scroll horizontal; **las tablas se vuelven tarjetas apiladas** (`.gw-cards`: cada fila una tarjeta con nombre arriba y **las acciones visibles en la misma tarjeta, sin desplazar**; caso real a corregir: en Formularios, «Editar» no se alcanza a ver en el celular); los cuadros emergentes pasan a hoja de pantalla completa (`.gw-modal` con modo hoja); la barra de guardado queda fija abajo y no tapa el último campo (relleno inferior); menú lateral plegado con botón; texto ≥ 16 px en campos (evita el zoom de iOS). Se prueba a 360 px, 768 px (iPad) y escritorio.
**R6 · Misma apariencia que las 6 pantallas nuevas.** Solo tokens `--gw-*` y clases `.gw-*` (`docs/ux/ESTANDARES_VISUALES.md`); ni `style=`, ni hex, ni `onclick=` en línea, ni emojis (íconos del sprite), `<body class="gw-page …">` + `_gw_head.html` + selector de tema claro/oscuro. Encabezado de página único (`.gw-page-head`: título, una línea de contexto, acción principal a la derecha, «?»). **Una sola acción principal (`gw-btn--primary`) por vista.**
**R7 · Los tres estados siempre:** vacío (qué es y cómo empezar), cargando (esqueleto o rueda) y error (qué pasó y qué hacer), en cada lista y en cada carga.
**R8 · Acciones peligrosas** (borrar, purgar, reembolsar, cerrar evento): en rojo, con `showConfirm` que nombra lo que se va a perder; nunca se cierran los formularios de datos al hacer clic afuera.
**R9 · Accesibilidad:** nombre accesible en todo control, foco visible, teclado completo (flechas en pestañas), contraste AA en claro y oscuro, movimiento reducido. Revisión con lector de pantalla (NVDA/VoiceOver) en las pantallas de la Ola 1.
**R10 · Candado automático para que no se pierda lo ganado.** Prueba global `tests/test_visual_global.py` con una lista (`MIGRADAS`) de plantillas ya terminadas: falla si una trae `style=`, hex, `onclick=` en línea, emoji, falta `gw-page`, tiene más de un `gw-btn--primary`, un botón solo-ícono sin `aria-label`, o más de un botón «Guardar». Cada PR agrega sus plantillas a la lista. Más: `tests/test_design_system.py` (pares de contraste) y `tests/js/params_save_check.js`.
**R11 · Cómo se prueba cada pantalla antes de pedirte el visto bueno:** claro y oscuro, 360 px / iPad / escritorio, solo teclado, guardado con red lenta y con error forzado, capturas antes/después en el PR. Tú apruebas el aspecto antes de fusionar. Nada pasa a producción sin tu orden «DESPLIEGA PRODUCCIÓN» (una entrega por tanda, nunca con un evento en proceso).

## 2. Piezas compartidas (Ola 0 — se hacen primero; sin esto no se arranca ninguna pantalla)
1. **`GWSave`**: capa fina sobre `params-save.js` para usarla en cualquier pantalla (no solo Parámetros): `GWSave.mount({bar, blocks[]})`, aviso al salir con cambios, `Ctrl/⌘+S`. Plantilla parcial `_gw_savebar.html`.
2. **`GW.busy()`** (rueda y bloqueo de doble clic en todo botón) + ajuste de `toast.js` (`showConfirm`/`showPrompt` pasan a `.gw-modal`; hoy conservan su aspecto propio).
3. **Móvil global**: mover el modo touch a `design-system.css`, cargar `touch-detect.js` desde `_gw_head.html`, componentes `.gw-cards` (tabla→tarjetas), `.gw-modal` (hoja en móvil), `.gw-page-head`, `.gw-empty`, `.gw-skeleton`. Documentar en `guia_visual.html` y `ESTANDARES_VISUALES.md`.
4. **Menú lateral y marco** (`_sidebar.html`, `_kiosk_top.html`, `_event_edit_modal.html`): objetivos táctiles de 44 px, plegable en celular, íconos del sprite.
5. **Registro de recorridos** `static/js/tours.js`: un solo archivo con los pasos de cada pantalla (§5) para no repetir código y poder traducir/ajustar textos en un sitio.
6. **`tests/test_visual_global.py`** (R10) con la lista `MIGRADAS` inicial = las 6 de hoy, y **`tests/test_publico_congelado.py`** (§0).
Criterio de listo de la Ola 0: Parámetros y Registro usan las piezas compartidas sin cambiar su aspecto; pruebas JS/CSS en verde; guía visual actualizada.

## 3. Orden de ejecución (olas y PRs)
Un PR por pantalla o grupo pequeño, desde `main`. Tamaño: S (≤ 1 día), M (1–2 días), L (3+ días).
| Ola | Contenido | PRs |
|---|---|---|
| 0 | Piezas compartidas (§2) + candado del público (§0) | 1–2 (M) |
| 1 · Día del evento | PR #52 Parámetros (ya abierto, se adapta a `GWSave`) · Registro: ventanas internas (editar, cámara, QR, MRZ, barra de impresión) · Elegir qué hacer (`kiosk_select`) + Inicio (`dashboard`) · Login/contraseña · Formularios (lista) · Rostro · Áreas · Inventario · Documentos · Legalizaciones · Certificados · Estadísticas · Ruleta y su pantalla del proyector | ~11 (S–M) |
| 2 · Configurar el evento | Usuarios del evento · Editor de formularios · Ruleta (configuración + apariencia) · Diseñador de escarapela y certificado (solo marco) · Impresora USB (solo marco) · Nuevo evento + Adjuntar base (ajustes) | ~6 (L el editor y el diseñador) |
| 3 · Administración | Eventos · Calendario · Clientes · Configuración · Usuarios del personal (`staff`) · Estado del sistema · Ventana «Editar evento» | ~7 (M) |
| 4 · Páginas públicas | **APLAZADA** (congeladas, ver §0): formulario público, consentimiento, escarapela digital, certificado, legales, proyector. Se decide aparte cuando no haya formulario activo | — |
Razón del orden: primero lo que se usa EL DÍA DEL EVENTO (donde el digitador no puede equivocarse), luego lo que arma el evento y por último administración. Lo público queda aplazado y quieto.

### Cómo se entrega (decisión 4)
- **Rama de integración `ux/fase-1-5`** (sale de `main` apenas se fusione el #58). Cada pieza es una rama `ux/<pantalla>` con su PR hacia `ux/fase-1-5` (pruebas en verde).
- **Staging, por piezas:** al terminar una pieza (o un lote), `ux/fase-1-5` se empuja a `migra/fase1-2` (la rama que despliega staging solo) y Juan la revisa en `https://golden-staging-298291650070.web.app`. No se crean recursos nuevos.
- **Producción, UNA sola entrega al final de la Fase 1.5:** PR `ux/fase-1-5` → `main`, y despliegue con la receta de siempre (copia de Neon, workflow manual con `confirm=DESPLEGAR`, verificación y punto de retorno) solo con la orden escrita de Juan David y sin evento en proceso ni por abrir. Como el formulario público está congelado, esa entrega no lo afecta.
- Si entre tanto hace falta un arreglo urgente en producción, sale aparte desde `main` y se vuelve a traer a `ux/fase-1-5`.

## 4. Inventario medido (5-nov-2026)
`style=` = estilos en línea; «Colores sueltos» = códigos de color escritos a mano; ya nuevo = usa `gw-page`.

| Plantilla | Ruta | style= | Colores sueltos | onclick | Emojis | Ya nuevo |
|---|---|---:|---:|---:|---:|:-:|
| `aceptar.html` | `?` | 1 | 14 | 0 | 0 | no |
| `aceptar_no_disponible.html` | `?` | 0 | 7 | 0 | 0 | no |
| `badge_editor.html` | `/kiosk/{event_id}/certificado, /kiosk/{event_id}/escarapela` | 36 | 75 | 0 | 19 | no |
| `badge_print.html` | `/kiosk/{event_id}/escarapela/imprimir/{user_id}` | 0 | 11 | 1 | 4 | no |
| `calendario.html` | `/calendario` | 27 | 19 | 0 | 6 | no |
| `certificate_public.html` | `/c/{token}` | 2 | 20 | 0 | 0 | no |
| `clientes.html` | `/clientes` | 17 | 21 | 1 | 4 | no |
| `configuracion.html` | `/configuracion` | 21 | 10 | 0 | 1 | no |
| `dashboard.html` | `/` | 9 | 6 | 0 | 1 | no |
| `digital_badge.html` | `/b/{token}` | 5 | 16 | 0 | 0 | no |
| `eventos.html` | `/eventos` | 10 | 12 | 0 | 4 | no |
| `form_public.html` | `/f/{event_id}/{slug}` | 36 | 22 | 0 | 5 | no |
| `form_stats.html` | `/kiosk/{event_id}/formularios/{form_id}/estadisticas, /mi-formulario, /ver/f/{to` | 5 | 0 | 0 | 0 | sí |
| `impresion_usb.html` | `/impresion-usb` | 2 | 9 | 0 | 1 | no |
| `kiosk_areas.html` | `/kiosk/{event_id}/areas` | 17 | 21 | 0 | 9 | no |
| `kiosk_certificados.html` | `/kiosk/{event_id}/certificados` | 6 | 3 | 0 | 0 | no |
| `kiosk_documentos.html` | `/kiosk/{event_id}/documentos` | 10 | 10 | 0 | 0 | no |
| `kiosk_estadisticas.html` | `/kiosk/{event_id}/estadisticas, /ver/e/{token}` | 39 | 36 | 0 | 4 | no |
| `kiosk_formulario_editor.html` | `/kiosk/{event_id}/formularios/{form_id}` | 268 | 58 | 0 | 62 | no |
| `kiosk_formularios.html` | `/kiosk/{event_id}/formularios` | 17 | 23 | 0 | 0 | no |
| `kiosk_inventario.html` | `/kiosk/{event_id}/inventario` | 19 | 19 | 0 | 2 | no |
| `kiosk_legalizaciones.html` | `/kiosk/{event_id}/legalizaciones` | 10 | 10 | 0 | 0 | no |
| `kiosk_parametros.html` | `/kiosk/{event_id}/parametros` | 0 | 0 | 0 | 0 | sí |
| `kiosk_registro.html` | `/kiosk/{event_id}, /kiosk/{event_id}/registro` | 0 | 0 | 0 | 0 | sí |
| `kiosk_roster.html` | `/kiosk/{event_id}/roster` | 0 | 0 | 0 | 0 | sí |
| `kiosk_rostro.html` | `/kiosk/{event_id}/rostro` | 0 | 13 | 0 | 0 | no |
| `kiosk_ruleta.html` | `/kiosk/{event_id}/ruleta` | 38 | 25 | 0 | 9 | no |
| `kiosk_ruleta_visual.html` | `/kiosk/{event_id}/ruleta/visual` | 12 | 9 | 0 | 0 | no |
| `kiosk_select.html` | `/kiosk/{event_id}` | 8 | 10 | 0 | 16 | no |
| `kiosk_usuarios.html` | `/kiosk/{event_id}/usuarios` | 11 | 7 | 3 | 0 | no |
| `legal_base.html` | `?` | 0 | 13 | 0 | 0 | no |
| `legal_privacidad.html` | `/privacidad, /privacidad/v1.0` | 0 | 0 | 0 | 0 | no |
| `legal_privacidad_v11.html` | `/privacidad` | 0 | 0 | 0 | 0 | no |
| `legal_reembolsos.html` | `/reembolsos` | 1 | 2 | 0 | 0 | no |
| `legal_terminos.html` | `/terminos` | 0 | 0 | 0 | 0 | no |
| `login.html` | `/login` | 2 | 1 | 0 | 0 | sí |
| `nuevo_evento.html` | `/clientes/{tenant_id}/nuevo-evento` | 18 | 6 | 0 | 0 | no |
| `password.html` | `/api/session/touch` | 17 | 6 | 0 | 0 | no |
| `roulette_display.html` | `/r/{token}` | 0 | 0 | 0 | 1 | no |
| `sistema.html` | `/sistema` | 9 | 22 | 0 | 0 | no |
| `staff.html` | `/admin/staff` | 13 | 7 | 8 | 2 | no |

Piezas sueltas fuera de plantillas (se limpian en la ola de su pantalla): `directory.js` (`buildEditModal`, `buildOfflineEditModal`), `camera-capture.js`, `qr.js`, `shared-print.js` (barra de impresión, solo CSS visual, jamás los parámetros), `option-tools.js`, `person-form-designer.js`, `toast.js`, `variant-table-ui.js`, `static/css/style.css` (hoja vieja: se vacía a medida que las pantallas migran y al final se borra).

## 5. Ficha por pantalla
Formato: **Ruta · quién** / **Hoy** / **Queda así** (secciones) / **Guardado** / **Guía de 3 pasos** / **Móvil** / **Ojo**. «Barra» = R1.

### Ola 1 · Día del evento
**Parámetros del evento** · `/kiosk/{id}/parametros` · coordinador+. Hoy: nuevo (PR #52 abierto). Queda: 8 pestañas ya hechas; adaptar a `GWSave`/`GW.busy`; pendientes de `PENDIENTES_VISUALES.md` (editor de opciones, diseñador del formulario de persona, avisos). Barra: ya. Móvil: pestañas con scroll y barra fija. Ojo: se fusiona primero; el formulario de persona sale encendido en producción.
**Registro** · `/kiosk/{id}/registro` · digitador+. Hoy: nuevo salvo las ventanas internas. Queda: «Editar persona» y edición sin red a `.gw-modal` (hoja en móvil), cámara y QR con tokens, «Registrar nuevo» con `.gw-field`, pestaña «Escáner de acceso» al estilo nuevo, barra de impresión solo visual. Barra: no aplica (cada alta/edición se guarda en su ventana con su propio botón + rueda). Guía: 1 busca, 2 acredita, 3 imprime. Móvil: ya tiene modo touch; pasa a la pieza global. Ojo: sin red (bandeja de salida) y impresión inamovible; probar contingencia.
**Elegir qué hacer** · `/kiosk/{id}` · todo el personal. Hoy: 16 emojis, 8 estilos. Queda: mosaicos grandes por tarea (`.gw-tile`) según rol (máx. 3 destacados), el resto en «Más herramientas» plegado. Barra: no. Guía: 1 elige el mosaico, 2 mira el estado del evento, 3 cambia de evento arriba. Móvil: mosaicos de una columna.
**Inicio** · `/` · personal. Hoy: lista «Eventos autorizados». Queda: tarjetas por evento con estado en insignia y botón «Entrar»; buscador. Guía: 1 busca tu evento, 2 mira el estado, 3 entra. (La mejora grande del inicio por rol es de la Fase 2.)
**Login y contraseña** · `/login` (nuevo), `password.html` · todos. Hoy: login ya nuevo; contraseña con 17 estilos. Queda: contraseña igual que login (`.gw-field`, política visible, barra de fuerza), botón con rueda. Barra: no (un botón). Móvil: una columna, teclado correcto.
**Formularios (lista)** · `/kiosk/{id}/formularios` · coordinador+. Hoy: tabla con 17 estilos; en celular «Editar» queda fuera de vista. Queda: tarjetas (`.gw-cards`) con nombre, estado (insignia), inscritos/cupo y los botones Editar · Estadísticas · Copiar enlace SIEMPRE visibles; «Crear» e «Importar» arriba, «Importar» plegado. Barra: no (acciones inmediatas con confirmación). Guía: 1 crea o importa, 2 edita y prueba, 3 activa y comparte el enlace. Móvil: caso de prueba oficial (360 px: Editar visible sin desplazar). Ojo: botón «estadísticas» y enlaces de solo lectura ya existen.
**Rostro** · `/kiosk/{id}/rostro` · operador. Hoy: 13 colores sueltos. Queda: panel de cámara + resultado con candidatos (foto de registro), estados claros (reconoce / dudoso / no está). Barra: no. Guía: 1 mira a la cámara, 2 verifica la foto, 3 confirma. Ojo: biometría: consentimiento y textos literales de la auditora no se tocan.
**Áreas · Inventario · Documentos · Legalizaciones** · `/kiosk/{id}/areas|inventario|documentos|legalizaciones` · digitador/coordinador. Hoy: 10–19 estilos y emojis cada una, tablas. Queda: encabezado + una acción principal («Registrar entrada», «Entregar», «Subir documento», «Registrar gasto»), listas como `.gw-cards` en móvil, vacío/cargando/error. Guardado: cada una guarda por operación (rueda); Legalizaciones y Documentos usan barra si tienen campos editables. Guías: Áreas 1 elige zona, 2 escanea/busca, 3 mira quién está dentro · Inventario 1 elige a quién, 2 qué se entrega, 3 confirma · Documentos 1 sube, 2 nómbralo, 3 compártelo · Legalizaciones 1 registra el gasto, 2 adjunta soporte, 3 revisa el total.
**Certificados** · `/kiosk/{id}/certificados` · coordinador+. Queda: asistente de 3 pasos (elegir plantilla → revisar → generar) con barra de avance. Ojo: el diseño del certificado es del diseñador (Ola 2).
**Estadísticas** · `/kiosk/{id}/estadisticas` y `/ver/e/{token}` (solo lectura, mismo marco) · coordinador+ / público. Hoy: 39 estilos, 36 colores. Queda: tarjetas de cifras + gráficos con la paleta de datos, filtros en una franja, tarjeta «Compartir» (ya existe) con el mismo estilo; la vista pública sin menús ni acciones. Barra: no. Guía: 1 elige la variable, 2 filtra, 3 comparte el enlace. Móvil: gráficos a ancho completo.
**Ruleta (configuración, apariencia, proyector)** · `/kiosk/{id}/ruleta`, `/ruleta/visual`, `/r/{token}` · coordinador+. Queda: pestañas «Cómo se elige» · «Premios» · «Apariencia» · «Sorteos»; apariencia con selector de color del sistema; la pantalla del proyector no cambia de comportamiento (solo tokens). Barra: ÚNICA para configuración y apariencia (hoy 2 «Guardar»). Guía: 1 define a quién incluye, 2 ajusta apariencia, 3 autoriza y gira. Ojo: pantalla del proyector a pantalla completa; probar sin red.

### Ola 2 · Configurar el evento
**Usuarios del evento** · `/kiosk/{id}/usuarios` · coordinador+. Hoy: tabla, 3 `onclick`. Queda: pestañas «Equipo» · «Digitadores temporales» · «Accesos y permisos»; cada persona una tarjeta con rol en insignia y acciones. Barra: única (hoy cada fila guarda sola). Guía: 1 agrega a alguien, 2 asigna el rol, 3 define vigencia. Ojo: reglas de permisos y digitador temporal no cambian; probar los 5 roles.
**Editor de formularios** · `/kiosk/{id}/formularios/{form_id}` · coordinador+. Hoy: 1.459 líneas, 268 estilos, 62 emojis, 12 escrituras, 4 «Guardar». Queda: pestañas «Campos» · «Cupos y variables» · «Reembolsos» · «Estado y enlaces» · «Seguridad» · «Pre-llenado» · «Idioma» · «Identificación (cédula)» con grupos plegables; vista previa a un lado (abajo en móvil); UNA barra de guardado (reemplaza los 4). Guía: 1 arma los campos, 2 pon cupos y cobros, 3 prueba y activa. Ojo: es la pantalla más grande; se divide en 2–3 PRs por pestañas; el motor de formularios y `form-render.js` (los comparte el formulario público) no se rompe; probar pago con la pasarela en pruebas.
**Diseñador de escarapela y de certificado** · `/kiosk/{id}/escarapela`, `/certificado` · coordinador+. Hoy: 1.224 líneas, 75 colores, 10 «Guardar». Queda: SOLO el marco: panel de propiedades en grupos, barra de herramientas, una barra de guardado; el lienzo y la composición de la etiqueta (`label-compose.js`, `badge-geometry.js`) NO se tocan. Guía: 1 elige elementos, 2 arrastra y ajusta, 3 imprime una prueba. Ojo: impresión inamovible: prueba física con la Brother antes de fusionar.
**Impresora USB** · `/impresion-usb` · admin. Queda: pasos 1 Conexión · 2 Etiqueta de prueba con estado claro. Ojo: no cambia ningún parámetro de impresión; prueba física.
**Nuevo evento** · `/clientes/{id}/nuevo-evento` · coordinador+. Hoy: 18 estilos. Queda: asistente de pasos (Datos · Fechas · Responsables · Revisar) con «Continuar»; barra de avance; al final «Crear» con rueda. Aviso: se crea con la persona «PRUEBA». Guía: 1 datos básicos, 2 fechas, 3 responsables.
**Adjuntar base (roster)** · ya nuevo; solo adaptar a `GW.busy` y revisar móvil.

### Ola 3 · Administración
**Eventos** · `/eventos` · personal. Queda: tarjetas con estado (insignia), cliente, ciudad, fechas; filtros (estado, cliente, comercial); acciones visibles. **Calendario** · `/calendario` · personal. Queda: mismo marco y filtros (el rediseño del contenido del calendario es de la Fase 2); 8 ventanas internas a `.gw-modal`; recordatorios con barra. **Clientes** · `/clientes` · coordinador+. Queda: tarjetas por cuenta, «+ Nuevo evento» destacado, crear cliente en grupo plegable. **Configuración** · `/configuracion` · admin. Queda: pestañas por tema + barra única (hoy 1 botón + ventana). **Usuarios del personal** · `/admin/staff` · admin. Queda: tarjetas, 8 `onclick` a delegación, cambio de rol con `showConfirm`. **Estado del sistema** · `/sistema` · super_admin. Queda: tarjetas de estado verde/ámbar/rojo con texto (no solo color). **Ventana «Editar evento»** (`_event_edit_modal.html`) → `.gw-modal`, barra de guardado propia (única, adentro). Guías de 3 pasos: Eventos (1 filtra, 2 entra, 3 cambia estado) · Calendario (1 mira el mes, 2 filtra, 3 crea recordatorio) · Clientes (1 busca, 2 abre la cuenta, 3 crea evento) · Configuración (1 elige la pestaña, 2 cambia, 3 guarda) · Staff (1 crea, 2 asigna rol, 3 revisa accesos) · Sistema (1 mira los semáforos, 2 abre el detalle, 3 qué hacer si hay rojo).

### Ola 4 · Páginas públicas — APLAZADA y congelada (§0)
Formulario público, consentimiento (`aceptar`), escarapela digital, certificado, páginas legales y pantalla del proyector no cambian. Lo único que se hace en esta fase relacionado: la **configuración** del formulario (editor, Ola 2) y los enlaces de estadísticas de solo lectura (usan la plantilla de Estadísticas, que sí se rediseña; es para clientes, no para asistentes).
**Fuera de alcance:** `badge_print.html` (impresión) y todo lo congelado en §0.

## 6. Criterios de «Fase 1.5 cerrada»
Todas las plantillas de administración/diseño (menos lo congelado de §0) en `MIGRADAS` con `tests/test_visual_global.py` verde · cero `style=`/hex/emojis/`onclick` en plantillas migradas · cada pantalla con su guía, «?» y recorrido (las públicas, sin recorrido) · una sola barra de guardado en cada pantalla que edita datos · rueda en todo botón con petición · prueba en 360 px / iPad / escritorio, claro y oscuro · `style.css` viejo vacío o borrado · `ESTANDARES_VISUALES.md` y `guia_visual.html` al día · revisión de accesibilidad con lector de pantalla en la Ola 1 · tu visto bueno del aspecto por tanda · UNA sola entrega a producción, con tu orden escrita, después de revisar todo en staging · `tests/test_publico_congelado.py` verde.

## 7. Riesgos y cómo se cubren
1. **Es mucho trabajo mezclado con la lógica** (editor de formularios, diseñador): se trocea por pestañas y no se toca lo que no es visual; pruebas existentes (`pytest`, `tests/js`) deben seguir verdes sin editarlas salvo por ids que se conserven.
2. **Choque con trabajo en curso:** se arranca desde `main` después de fusionar el #58 y el #52; cada PR toca pocas plantillas.
3. **Regresiones sin red (contingencia) e impresión:** pruebas de contingencia por PR del Registro y prueba física con la Brother en toda pieza que toque impresión.
4. **Entrega a producción:** una sola, nunca con un evento en proceso ni a punto de abrir; sin `force`. El formulario activo no se ve afectado (§0).
5. **Cansancio de cambio para el equipo:** el recorrido de primera vez en cada pantalla y la regla de «lo frecuente a la vista» (docs/ux).

## 8. Decisiones (respondidas por Juan David el 5-nov-2026)
1. Orden de olas: aprobado.
2. Ctrl/⌘+S + botón + aviso de cambios pendientes en todas las pantallas con barra: sí.
3. Formulario público: congelado, sin cambios visuales por ahora (hay uno activo). Lo público se decide después.
4. Staging por piezas; producción en una sola entrega al final.
