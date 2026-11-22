# 06 · Usabilidad de las pantallas de gestión (coordinador · comercial · admin) — 22-nov-2026

Rol de esta revisión: tres pasadas (coordinador de evento, incluido el temporal `event_only`; comercial; admin que no es super_admin) y una tercera de crítica cruzada. Se leyeron las plantillas de gestión, `app/auth.py`, `app/event_only.py`, `app/routers/parametros.py` y `events.py`, y se MIRARON las pantallas con el servidor de maquetas (datos ficticios) a 390, 1024 y 1440 px. Las capturas quedaron en `/tmp/claude-0/-home-claude/c8439ba9-1a71-51c4-99fe-c272d745a86e/scratchpad/vis/out/u6_*.png` (no van al repo).

## 1. Resumen en 5 líneas
1. **Las pantallas rediseñadas (Fase 1.5) están bien resueltas:** guía de 3 pasos con «?», un solo «Guardar cambios», «Al instante» marcado, vista previa obligatoria al cargar bases, y las acciones realmente destructivas (borrar base, borrar fotos del evento, borrar un campo) piden ESCRIBIR una palabra o un nombre. Parámetros tiene 32 ayudas ⓘ para 27 bloques (24 bloques con ⓘ en su título).
2. **Lo más grave:** cuatro acciones costosas se confirman con un simple «Sí/No» igual al de cualquier cosa: *Suprimir TODOS los datos de una persona* (Parámetros › Privacidad), *Eliminar los usuarios temporales de este evento* (botón rojo grande al lado de «Autorizar a todos»), *reembolsar un pago por Wompi* y *reabrir un evento Finalizado* (pasa a «En Proceso» con «¿Cambiar el estado…?»). Y **publicar un formulario con pago** («Activo») no pedía ninguna confirmación: bastaba cambiar el desplegable y pulsar Guardar (o Ctrl+S).
3. **Lo que más tiempo hace perder:** el menú del evento tiene 18 mosaicos sin orden de preparación y «Parámetros del evento» (donde se activa TODO) está de último con una descripción que hablaba solo de campos; el asistente de «Nuevo evento» termina en la lista de eventos sin decir cuál es el siguiente paso; y crear un formulario con pago exige saber que la cuenta de cobro se asigna en OTRA pantalla (Cuentas de cobro), porque el editor del formulario no la menciona.
4. **Jerga técnica visible es poca y está localizada:** `SESSION_IDLE_MINUTES`, `SINGLE_SESSION`, `OFFSITE_FOLDER_URL`, comandos `gcloud`/`gsutil`/`git checkout f5/integracion` dentro de Configuración (admin), «URL de eventos (webhook)» en Cuentas de cobro, `text_short`/`super_event` en el diseñador de plantilla, `cedula_titular` en dependientes, y el rol crudo `(super_admin)` en el encabezado de todas las pantallas.
5. **Lo más valioso ya construido:** la vista previa de la carga de base (resumen + impacto + 10 personas) y las confirmaciones «escribe el nombre» son el estándar que hay que copiar a las cuatro acciones del punto 2. `/sistema` es solo lectura: desde ahí no se puede dañar producción.

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | **Alta** | «Suprimir TODOS los datos de esta persona» y «Revocar autorización» se confirman con un Sí/No; la cédula se escribe a mano en una caja aparte y un dígito mal escrito suprime a otra persona. | `templates/kiosk_parametros.html` › Privacidad (`privAll`, `privRevoke`, líneas 926-937) | Es irreversible (anonimiza ingresos y borra rostro). Contrasta con «Borrar los datos del rostro de TODO el evento», que sí exige escribir el nombre del evento. | **Propuesto** (JS, fuera de mi área): antes de confirmar mostrar nombre y apellidos de la cédula escrita y exigir escribir la cédula de nuevo (misma maqueta que `biometric-purge.js`). |
| 2 | **Alta** | «Eliminar los usuarios temporales de este evento» es un botón rojo RELLENO, del mismo tamaño y en la misma fila que «Autorizar a todos los pendientes»; confirma con Sí/No. | `templates/kiosk_usuarios.html` línea 206-208; `static/js/usuarios.js` línea 435 | El día del evento el coordinador pulsa «Autorizar a todos» con prisa; el vecino borra TODAS las cuentas de digitador (no se recuperan). | **Propuesto**: moverlo al final de la lista como `gw-btn--danger-outline` pequeño y exigir escribir «ELIMINAR». |
| 3 | **Alta** | Publicar un formulario (estado «Activo») no pedía confirmación: cambiar el desplegable y guardar (o Ctrl+S) abre el enlace público y, con campo de pago, cobra dinero real. | `templates/kiosk_formulario_editor.html` líneas 149-154 y 1237-1255 (`saveAll`) | Un formulario a medio diseñar o con el precio mal queda abierto al público sin aviso. | **Corregido en texto** (aviso en la ayuda bajo el estado). **Propuesto**: `showConfirm` con `variant: 'warning'` al pasar a Activo cuando `pendingStatusChange()` y hay campo `payment` («Se cobrará dinero real desde ya»). |
| 4 | **Alta** | Reembolsar un pago por la API de Wompi (dinero que sale) se confirma con un Sí/No genérico. | `kiosk_formulario_editor.html` línea 1745 | No se puede deshacer; el monto se escribe a mano. | **Propuesto**: mostrar monto, referencia y cédula en el cuadro y exigir escribir el monto. |
| 5 | **Media** | Un evento «Finalizado» se reabre a «En Proceso» desde el desplegable de la tarjeta con «¿Cambiar el estado del evento a "En Proceso"?». El backend lo permite (`events.py` 578-592 solo frena la vuelta a Creado). | `templates/eventos.html` 313-338; `static/js/toast.js` 68-71 | Reabrir reactiva el registro, los formularios y el acceso de coordinadores temporales (que vence al finalizar), sin decirlo. El desplegable de estado está en TODAS las filas, al lado de «Ingresar». | **Propuesto**: texto propio para «Finalizado → En Proceso» en `confirmStatusChange` (qué se reactiva) y mover el estado a «Editar» o al menú «Más acciones» en Eventos. |
| 6 | **Media** | El menú del evento tiene 18 mosaicos (6 «de todos los días» + 12 en «Más herramientas»), sin el orden de preparación (Parámetros → Base → Escarapela → Usuarios → Formularios). «Parámetros del evento» va de ÚLTIMO y su descripción hablaba solo de campos. Hay dos mosaicos llamados «Inventario» y «Control de inventario». | `templates/kiosk_select.html` 95-153 | Prueba de 5 segundos fallida para un coordinador nuevo: no sabe por dónde empezar. | **Corregido en texto** (descripción de «Parámetros del evento» e «Inventario»). **Propuesto**: con el evento en «Creado», un bloque «Prepara el evento» con 4 pasos en orden y marca ✔ de lo hecho (hay base, hay escarapela, hay digitadores). |
| 7 | **Media** | «Nuevo evento» termina en la lista de eventos (`AFTER_URL`) sin decir qué sigue; la franja «1·2·3» de la guía se lee como si el asistente tuviera 3 pasos cuando dice «Paso 1 de 4». | `templates/nuevo_evento.html`; `static/js/nuevo-evento.js` 283-288 | Para registrar hace falta aún: Parámetros, base, escarapela, pasar a «En proceso». Nadie lo dice. | **Corregido en texto** (aria-label de la guía). **Propuesto**: al crear, cuadro «Evento creado. ¿Qué sigue?» con botones «Configurar parámetros», «Cargar la base», «Ir a la lista». |
| 8 | **Media** | Crear un formulario con pago exige asignar la cuenta de cobro en otra pantalla (Cuentas de cobro › «Formularios y QR»); el editor del formulario no menciona la cuenta ni enlaza allá. | `kiosk_formulario_editor.html` (0 menciones a «cuenta de cobro»); `templates/cuentas_cobro.html` | La comercial cree que el pago quedó listo; sin cuenta cobra la de Golden sin que ella lo sepa. | **Propuesto**: en la pestaña «Pagos» del editor, una línea «Cobra con: <cuenta> · Cambiar (abre Cuentas de cobro)». |
| 9 | **Media** | La ventana «Editar evento» tiene 12 secciones y ~30 campos, 0 ayudas ⓘ, y repite «Estado del evento». Términos sin explicar: «Jornada», «Superevento y pañoleta», «Servidor local (sin internet)», «Enlace de entrega al cliente». | `templates/_event_edit_modal.html` | Es la pantalla que más abre la comercial (base final, informe, facturado). | **Propuesto**: ⓘ en cada sección y cerrar por defecto las que no aplican al rol. |
| 10 | **Media** | Configuración › Apariencia dice «solo de este computador» pero dentro trae «Tamaño del logo (Para todos)» y «Tiempo de sesión (Para todos)»; el botón «Restablecer» no decía qué restablece. | `templates/configuracion.html` 89-132 | Un admin cree que el tiempo de sesión es local, o teme que «Restablecer» toque lo de todos. | **Corregido en texto** (etiqueta del botón). **Propuesto**: mover los dos «Para todos» a la pestaña «Sesiones» → «General». |
| 11 | **Media** | Rol del personal sin ayuda: el desplegable ofrece Coordinador, Director de coordinadores, Comercial, Almacén y Contabilidad sin ⓘ; el subtítulo decía que solo se crean Coordinador y Comercial. En Usuarios del evento, «Digitador (temporal)» / «Cliente (temporal)» / «Coordinador (temporal)» tampoco tienen ⓘ. | `templates/staff.html` 53, 88-95; `templates/kiosk_usuarios.html` 115-122 | El admin da un rol de más o de menos. | **Corregido en texto** (subtítulo de Staff). **Propuesto**: ⓘ por rol con «qué puede / qué NO puede». |
| 12 | **Media** | «Permitir» el ingreso de cada digitador exige que un coordinador esté mirando la pantalla cuando el digitador entra por primera vez; solo admin ve «Autorizar a todos». | `kiosk_usuarios.html` 206; `usuarios.js` 81 | A las 6 a. m. del evento, con 20 digitadores, es la cola más lenta del día. | **Propuesto**: «Autorizar a todos» también para el coordinador del evento, o pre-autorización al crear la cuenta. |
| 13 | **Baja** | Jerga visible para admin: `SESSION_IDLE_MINUTES`, `SINGLE_SESSION`, `OFFSITE_FOLDER_URL`, bloque «Cómo publicar el instalador» con `gcloud`, `gsutil`, `gh`, `git checkout f5/integracion` (rama que ya no es la de producción). | `templates/configuracion.html` 125, 223, 274, 157-192 | Un admin de oficina no debe ver comandos; la rama citada está desactualizada. | **Propuesto**: mover «Cómo publicar el instalador» a `docs/` y dejar solo «pídelo a soporte»; reemplazar nombres de variables por «lo fija el servidor». |
| 14 | **Baja** | Jerga visible para comercial/coordinador: «URL de eventos para pegar en Wompi (webhook)» en Cuentas de cobro; `text_short`, `text_long`, `super_event`, `bandana_colors` en el diseñador de plantilla; `cedula_titular`, `nombre_dependiente` en dependientes; el encabezado muestra el rol crudo `(super_admin)`, `(admin)`. | `static/js/cuentas-cobro-page.js` 72; `templates/plantilla_evento.html`; `kiosk_roster.html` 207-208; todas las cabeceras (`{{ staff_role }}`) | Rompe el principio «dummy» aunque no bloquea. Las columnas de dependientes sí deben seguir así (son nombres de columna del archivo). | **Propuesto**: etiquetas en español en el diseñador (los valores internos siguen igual) y `ROLE_LABELS` en la cabecera. |
| 15 | **Baja** | Parámetros › Impresión › «Valores de la QL-800»: 11 controles técnicos (Giro, Espejo, Invertir, Margen de avance, Recortar al contenido…) con UNA sola ⓘ para el bloque. Son los parámetros INAMOVIBLES: un coordinador curioso los cambia para todo el evento. | `kiosk_parametros.html` 329-347 | Dañar la impresión de un evento entero sin querer. | **Propuesto**: plegar el bloque con «Avanzado · no cambiar salvo indicación de soporte» y ⓘ por control (respetando `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`). |
| 16 | **Baja** | Lista de eventos vacía decía «Los eventos se crean desde la ficha de cada cliente» mientras arriba hay «Nuevo evento». | `templates/eventos.html` 255 | Contradicción en la primera pantalla. | **Corregido**. |
| 17 | **Baja** | Usuarios del evento mezcla acciones «al instante» con dos casillas que sí requieren «Guardar cambios» (aviso por correo, exigir compromiso); el comentario de la plantilla dice «sin barra de guardado» pero la incluye. | `kiosk_usuarios.html` 144, 196, 218 | El coordinador marca la casilla, no guarda y se va. | **Propuesto**: pasar las dos casillas a «Al instante» (PUT al cambiar) y quitar la barra. |
| 18 | **Baja** | Coordinador temporal (`event_only`): no ve «Nuevo evento» ni «Duplicar» (correcto) pero sí el desplegable de estado de sus eventos, y «Finalizar» le CORTA su propio acceso (la autorización vence al finalizar) sin que el aviso lo diga. | `app/event_only.py`; `app/auth._scope_applies`; `toast.js` `FINALIZE_CONFIRM` | Se queda por fuera del evento que acaba de cerrar, sin el reporte. | **Propuesto**: en `FINALIZE_CONFIRM` para `event_only`: «Al finalizar dejarás de ver este evento: descarga el reporte antes». |

### 2.1 Parámetros del evento: tamaño real de la pantalla (maqueta, rol admin, facial apagado)

| Pestaña | Bloques | Bloques con ⓘ en el título | Controles (casillas, listas, cajas) | Ayudas ⓘ | Marcas «Al instante» |
|---|---|---|---|---|---|
| Registro y pantalla | 5 | 5 | 15 | 5 | 1 |
| Reconocimiento facial | 1 (+1 solo super_admin) | 1 | 10 | 3 | 0 |
| Invitaciones | 5 | 3 | 4 | 5 | 2 |
| Impresión y reimpresión | 4 | 4 | 13 | 4 | 0 |
| Escarapelas y certificados | 2 | 2 | 8 | 4 | 0 |
| Zonas e inventario | 5 | 5 | 46 | 6 | 2 |
| Campos | 3 | 3 | 49 (tabla de campos) | 4 | 0 |
| Privacidad | 2 | 1 | 4 | 1 | 1 |
| **Total** | **27** | **24** | **~149** | **32** | **6** |

Configuración (admin): 9 pestañas, 16 bloques, 13 con ⓘ, 29 controles. Las pestañas «Plantilla de eventos», «Copias de seguridad» y «Staff y permisos» no tienen ninguna ⓘ (la última es un iframe de `/admin/staff`).

### 2.2 Clics por tarea (contados en plantillas y JS; sin contar escribir)

| Tarea | Clics | Dónde se pierde tiempo |
|---|---|---|
| Crear un evento desde cero hasta poder registrar | **10** (Nuevo evento 1 · Continuar ×3 · Crear 1 · estado «En Proceso» 2 · confirmar 1 · Ingresar 1 · Registro 1) + ~12 campos obligatorios | Después de «Crear evento» cae en la lista; nadie dice que faltan Parámetros, base y escarapela. Registrar de verdad exige además pasar a «En proceso» (solo PRUEBA se registra en «Creado»). |
| Cargar la base | **6** (Ingresar · Adjuntar base · elegir archivo 2 · Cargar lista · confirmar vista previa) | Bien: vista previa, plantilla descargable, «¿Subiste una base equivocada?» con palabra BORRAR. |
| Diseñar la escarapela | **5 + diseño** (Ingresar · Escarapelas · elementos · Guardar · imprimir prueba con PRUEBA desde Registro: 3) | El diseñador no ofrece «Imprimir prueba» desde sí mismo (paso 3 de su guía dice «Guarda e imprime una prueba» pero manda a Registro). |
| Crear un formulario con pago | **10 + 5** (Ingresar · Formularios · Crear · arrastrar «Pago (Wompi)» · precio · Guardar · Configuración · Activo 2 · Guardar · Copiar enlace; + Cuentas de cobro: Agregar · datos · asignar formulario · Guardar) | La cuenta de cobro vive en otra pantalla (hallazgo 8). Sin confirmación al activar (hallazgo 3). |
| Dar acceso a un digitador | **4 + 1** (Ingresar · Usuarios del evento · Crear y asignar · «Permitir» cuando intenta entrar) | El «Permitir» es síncrono con el primer ingreso (hallazgo 12). |
| Cerrar el evento y sacar el reporte | **6** (estado «Finalizado» 2 · confirmar 1 · Ingresar · Estadísticas · Exportar base de datos (Excel)) + 4 para adjuntar la base final en Editar (obligatoria para «Facturado») | Dos descargas distintas («Exportar base de datos» en Estadísticas y «Base de datos final» en Editar) sin explicar la diferencia. |

### 2.3 Acciones destructivas y su confirmación (inventario)

| Acción | Confirmación hoy | Proporcional |
|---|---|---|
| Borrar la base cargada (roster) | Escribir **BORRAR** + cuenta de personas | Sí |
| Borrar los datos del rostro de TODO el evento | Escribir el **nombre del evento** + cuántos rostros | Sí |
| Borrar un campo del evento | Escribir el **nombre del campo** + uso en plantillas/formularios | Sí |
| Devolver evento a «Creado» | Ventana propia (`revert-event.js`) con rastro | Sí |
| Finalizar evento | Texto propio (7 días, se puede reabrir) | Sí (falta el aviso para `event_only`) |
| Suprimir TODOS los datos de una persona | Sí/No | **No** (hallazgo 1) |
| Eliminar los usuarios temporales del evento | Sí/No | **No** (hallazgo 2) |
| Reembolso por API de Wompi | Sí/No | **No** (hallazgo 4) |
| Formulario → Activo (con pago) | Ninguna (solo la barra de guardado) | **No** (hallazgo 3) |
| Reabrir evento Finalizado | «¿Cambiar el estado…?» genérico | **No** (hallazgo 5) |
| Eliminar cuenta de staff / digitador | Sí/No, texto explica que no se deshace | Aceptable (el backend impide borrar coordinador/comercial de un evento) |
| Eliminar zona / ítem de inventario | Sí/No; el backend solo lo permite sin movimientos | Aceptable |
| Eliminar una inscripción de formulario | Sí/No | Aceptable |
| `/sistema` | Solo lectura (`GET /api/ops/status`) | No hay riesgo |

## 3. Qué se cambió en el código (solo textos; sin tocar ids, clases, estructura ni JS)
- `templates/eventos.html`: el estado vacío ya no contradice al botón «Nuevo evento».
- `templates/kiosk_select.html`: descripción del mosaico «Parámetros del evento» (dice que ahí se activa todo y que es el primer paso en un evento nuevo) y del mosaico «Inventario» (equipos de Golden, no lo que se reparte).
- `templates/staff.html`: el subtítulo nombra los cinco roles que de verdad ofrece el desplegable.
- `templates/configuracion.html`: el botón «Restablecer» dice qué restablece («el color y la tipografía de este computador»).
- `templates/kiosk_formulario_editor.html`: la ayuda bajo «Estado» advierte que «Activo» abre el enlace de verdad y cobra dinero real si hay campo de pago.
- `templates/nuevo_evento.html`: la franja de guía ya no se llama «Guía de 3 pasos» (el asistente tiene 4).

Pruebas: `python3 -m pytest --noconftest -q` sobre los 22 archivos de `tests/` que mencionan esas plantillas → **131 pasaron**; 35 «errores» son solo `fixture 'client' not found` (necesitan la base de datos, no corren sin `conftest`) y 2 archivos no importan sin `sqlalchemy` en este entorno. `ruff check .` → sin observaciones. Las seis plantillas siguen renderizando en el servidor de maquetas.

## 4. Qué queda pendiente y por qué (orden recomendado)
1. **Confirmaciones fuertes** para suprimir persona, eliminar usuarios temporales y reembolso Wompi (hallazgos 1, 2, 4): 3 h. JS en `kiosk_parametros.html`, `usuarios.js`, `kiosk_formulario_editor.html` + prueba de texto. No lo hice porque toca JS (fuera de mi área).
2. **Confirmar «Activo» con pago** y «Cobra con: cuenta» en el editor de formularios (hallazgos 3 y 8): 3 h.
3. **Reabrir Finalizado** con texto propio y estado fuera de la fila en Eventos (hallazgo 5): 2 h.
4. **«¿Qué sigue?» al crear evento + bloque «Prepara el evento» en el menú del evento** (hallazgos 6 y 7): 5 h (JS + plantilla + 1 endpoint de progreso).
5. **ⓘ por rol** en Staff y Usuarios del evento; ⓘ en Editar evento (hallazgos 9, 11): 3 h.
6. **Mover lo «Para todos» a Sesiones; sacar los comandos de Configuración** (hallazgos 10, 13): 2 h.
7. **Autorizar a todos para el coordinador**; casillas de Usuarios «al instante» (hallazgos 12, 17): 2 h.
8. **Etiquetas en español** en diseñador de plantilla y rol legible en cabecera (hallazgo 14): 2 h.
9. **Bloque QL-800 plegado como «Avanzado»** (hallazgo 15): 1 h, respetando los parámetros inamovibles.
Total estimado: **23 h**.

## 5. Qué NO se pudo comprobar
- No se probó contra staging ni producción (el encargo no lo pide): todo es lectura de código y maquetas con datos ficticios. Los flujos reales (clic a clic con base de datos) se contaron en plantillas y JS, no se cronometraron.
- El servidor de maquetas no simula varias llamadas de Parámetros (`sin simular`): las tablas de zonas, inventario, puestos y campos se vieron vacías; la cuenta de controles de «Campos» (49) sale de la tabla sin filas de datos reales.
- No se abrieron con maqueta: el diseñador de escarapelas (`badge_editor.html`), el editor de formularios, el calendario, Legalizaciones ni el CRM (leídos solo en código). El coordinador temporal se evaluó por `app/event_only.py` y `auth.py`, no entrando con una cuenta `ct-`.
- Las 2 pruebas con base (`test_ajustes_sabado17.py`, `test_facturado.py`) no corren aquí (falta `sqlalchemy` en el entorno); mis cambios son solo textos, pero esos archivos quedan por correr en la suite final.

## 6. Consejo en corto
- **Contrario:** «No agregues más ⓘ: ya hay 32 en Parámetros y nadie las lee; quita opciones de la vista del coordinador (QL-800, pre-cálculo) en vez de explicarlas».
- **Primeros principios:** «Una acción irreversible debe costar lo mismo siempre: escribir una palabra. Hoy depende de quién la programó».
- **Expansionista:** «El bloque "Prepara el evento" con ✔ es el inicio del onboarding del SaaS: cada cliente nuevo lo necesitará».
- **Forastero:** «Entré a un evento y vi 18 cuadros; el que lo arma todo estaba de último. Eso es lo primero que vería un cliente que compre el servicio».
- **Ejecutor:** «Las tres confirmaciones fuertes (persona, usuarios temporales, reembolso) son 3 horas y cierran los riesgos Alta; hazlas antes que cualquier rediseño».

**Veredicto:** la gestión es usable y bastante segura, pero hay cuatro puertas irreversibles con el mismo «Sí/No» que una acción trivial. **Siguiente paso único:** aplicar el patrón «escribe el nombre/la cédula/ELIMINAR» (el mismo de `biometric-purge.js`) a suprimir persona, eliminar usuarios temporales y reembolsar por Wompi, con su prueba de texto.
