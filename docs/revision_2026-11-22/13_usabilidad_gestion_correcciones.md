# 13 · Usabilidad de gestión: correcciones aplicadas (developer de front) — 22-nov-2026

Rol: aplicar las correcciones ACOTADAS del reporte [06](06_usabilidad_gestion.md), sin cambiar estructura de datos ni endpoints. Solo plantillas, JS del navegador, CSS al final de `design-system.css` y pruebas. Sin commit ni push (los hace el coordinador).

## 1. Resumen en 5 líneas
1. **Las cinco puertas irreversibles con «Sí/No» ya cuestan lo mismo: escribir una palabra.** Suprimir todos los datos de una persona (SUPRIMIR), revocar la autorización del rostro (REVOCAR), eliminar los usuarios temporales (ELIMINAR), reembolsar por Wompi (REEMBOLSAR) y reabrir un evento finalizado (REABRIR). El botón de confirmar sale en rojo.
2. **Publicar un formulario que cobra ya no es silencioso:** al guardar con «Activo» y campo de pago sale un aviso que dice que cobra dinero real y con qué cuenta; y bajo el estado aparece «Cobra con: …» (o «(sin asignar) → asignar en Cuentas de cobro»).
3. **«Nuevo evento» termina con «¿Qué sigue?»:** tres pasos con su enlace (cargar la base, diseñar la escarapela, dar acceso a digitadores). El guardado no cambió.
4. **Menos jerga y más ayuda:** ⓘ por rol en Staff (5) y en Usuarios del evento (3), ⓘ en las 13 secciones de «Editar evento», comandos y variables de Configuración dentro de «Avanzado (solo técnicos)» con el texto exacto, rol legible en la cabecera de 8 pantallas, y los valores de la QL-800 plegados sin tocar ninguno.
5. **Lo más grave que queda:** el desplegable de estado sigue en cada fila de Eventos (ahora protegido, pero a un clic), y el bloque «Prepara el evento» del menú del evento no se hizo (necesita un endpoint, fuera de mi área).

## 2. Hallazgos (numeración del reporte 06)

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | Alta | Suprimir TODOS los datos y Revocar se confirmaban con Sí/No | Parámetros › Privacidad | Irreversible; un dígito mal escrito borra a otra persona | **Corregido**: hay que escribir SUPRIMIR / REVOCAR; el texto muestra la cédula y pide revisarla dígito por dígito. Mismo endpoint. **Pendiente**: mostrar el NOMBRE de la persona (ver §4) |
| 2 | Alta | «Eliminar los usuarios temporales» era un botón rojo relleno al lado de «Autorizar a todos» | Usuarios del evento | Un clic de prisa borraba todas las cuentas | **Corregido**: salió de esa fila; ahora es un botón pequeño con borde, en una zona «Al terminar el evento» al final de la lista, y pide escribir ELIMINAR |
| 3 | Alta | Pasar un formulario con pago a «Activo» no pedía confirmación | Editor de formularios | Cobros reales sin aviso | **Corregido**: confirmación explícita ANTES de guardar nada (si se cancela no cambia nada); dice «cobra dinero real» y la cuenta |
| 4 | Alta | Reembolso por Wompi con Sí/No | Editor de formularios › Pagos | Dinero que sale, sin vuelta atrás | **Corregido**: muestra monto y referencia y pide escribir REEMBOLSAR. El reembolso «manual» (solo registro) conserva su Sí/No |
| 5 | Media | Reabrir un evento Finalizado usaba el genérico «¿Cambiar el estado…?» | Eventos | Reactiva registro, formularios y accesos sin decirlo | **Corregido en Eventos**: texto propio (qué se reactiva; el plazo de 7 días de los rostros se detiene y empieza de cero al volver a finalizar; lo ya borrado no vuelve) y escribir REABRIR. **Pendiente**: lo mismo en Clientes y Calendario, y sacar el desplegable de la fila |
| 7 | Media | «Nuevo evento» volvía a la lista sin decir qué sigue | Nuevo evento | Nadie decía que faltan base, escarapela y digitadores | **Corregido**: cuadro «Evento creado. ¿Qué sigue?» con 3 enlaces y «Ir a la lista de eventos» |
| 8 | Media | El editor no decía qué cuenta cobra | Editor de formularios | La comercial cree que el pago quedó listo | **Corregido** (solo lectura): línea «Cobra con: …» bajo el estado; sin cuenta: «(sin asignar) → asignar en Cuentas de cobro» (enlace solo para administradores, que son quienes pueden abrirla) |
| 9 | Media | «Editar evento» sin ninguna ayuda | Ventana Editar evento | Términos sin explicar (jornada, superevento, servidor local…) | **Corregido**: una ⓘ por sección (13). Pulsarla no pliega la sección |
| 11 | Media | Roles sin explicación | Staff; Usuarios del evento | Se da un rol de más o de menos | **Corregido**: ⓘ por rol con «Puede / No puede» y su lugar en la escalera |
| 13 | Baja | Comandos y nombres de variables a la vista | Configuración | Un admin de oficina no debe ver comandos | **Corregido**: texto visible en español llano («lo fija el servidor, pídelo a soporte») y el texto original, EXACTO, dentro de «Avanzado (solo técnicos)» |
| 14 | Baja | Rol crudo `(super_admin)` en cabeceras; `text_short`, `webhook` | Cabeceras; diseñador de plantilla; Cuentas de cobro | Rompe el lenguaje llano | **Corregido en 8 pantallas** (cabecera: «Administrador general», «Administrador»…). `webhook` ya no se ve en Cuentas de cobro y `text_short` ya sale como «Texto corto» en Parámetros y en el editor de formularios (lo comprobé, no hubo que cambiar nada). **Pendiente**: las demás cabeceras (≈30 plantillas de otros agentes) |
| 15 | Baja | 11 controles de la QL-800 a la vista | Parámetros › Impresión | Un curioso daña la impresión del evento | **Corregido**: plegado como «Avanzado (no cambiar salvo indicación de soporte)» con aviso. Ningún valor, id, límite ni control cambió |
| 6, 10, 12, 17, 18 | Media/Baja | Menú del evento sin orden; «Para todos» dentro de Apariencia; «Autorizar a todos» solo admin; casillas que piden Guardar; aviso al coordinador temporal al finalizar | Varias | Ver reporte 06 | **Pendiente** (§4) |

## 3. Qué se cambió en el código
**Archivos nuevos**
- `static/js/gw-confirm-typed.js`: `GWConfirm.typed(...)` (pide escribir una palabra, sobre `showPrompt` de `toast.js`; no cuentan mayúsculas ni tildes), los textos de las cinco confirmaciones en un solo lugar, `reopenEvent`, `activatePaidForm` y `accountLine`.
- `static/js/gw-summary-help.js`: evita que pulsar una ⓘ puesta en el título de un grupo plegable lo abra o lo cierre.
- `templates/_gw_role_name.html`: macro `role_name(rol)` con los mismos nombres que ya usaba la cabecera del Registro.
- `tests/test_usabilidad_gestion_2026-11-22.py` (14 pruebas de texto) y `tests/js/gw_confirm_typed_check.js` (lógica pura, con Node).

**Archivos modificados**
- `templates/kiosk_parametros.html`: Privacidad usa la confirmación escrita; bloque QL-800 dentro de `<details class="gw-advanced" id="psAdvanced">`; cabecera con rol legible.
- `templates/kiosk_usuarios.html` y `static/js/usuarios.js`: zona de peligro al final (`#purgeTempZone`), confirmación ELIMINAR, ⓘ de los tres roles temporales.
- `templates/kiosk_formulario_editor.html`: reembolso con REEMBOLSAR; confirmación al activar con pago dentro de `saveAll`; línea `#payAccountLine`. Lee `form.payments.account_id` (ya venía en el API) y, solo si es administrador, `GET /api/payment-accounts` para decir el nombre.
- `templates/eventos.html`: Finalizado → En proceso usa `GWConfirm.reopenEvent`.
- `static/js/nuevo-evento.js`: `showNextSteps(created)` tras la respuesta correcta del servidor.
- `templates/staff.html`: ⓘ de los cinco roles. `templates/_event_edit_modal.html`: ⓘ en 13 secciones.
- `templates/configuracion.html`: cuatro «Avanzado»; no se tocó la tarjeta de llaves del servidor local del otro agente.
- `templates/nuevo_evento.html`, `templates/cuentas_cobro.html`: solo la cabecera.
- `static/css/design-system.css` (al final, solo tokens): `.gw-rolehelp`, `.gw-advanced`, ⓘ dentro de `.gw-form-group__summary`.
- `tests/test_parametros_visual.py`: una afirmación comprobaba el Sí/No antiguo de Privacidad; ahora comprueba la confirmación escrita.

**Pruebas.** Antes y después, sobre los 45 archivos de `tests/` que mencionan estas pantallas más impresión y sistema de diseño (`--noconftest`): antes 209 pasan / 3 fallan; después 223 pasan / 3 fallan. Los 3 fallos son los MISMOS y ajenos a este trabajo (`test_codigo_campo` 1, `test_privacy` 2); los 102 «errores» son pruebas que necesitan la base. `tests/test_impresion_parametros_fijos.py` y `tests/test_design_system.py` en verde. `ruff check .` sin observaciones. Los bloques de script de las plantillas tocadas, ya renderizadas, pasan `node --check`.

**Visto en la maqueta** (Playwright, 1280 y 390 px): zona de peligro y ⓘ de rol en Usuarios, ⓘ en Editar evento (abre, «Entendido» cierra, la sección no se pliega), «¿Qué sigue?», confirmación de suprimir, QL-800 plegado, «Avanzado» de sesión única y cabecera «(Administrador general)». Corregido al mirar: la ayuda de rol se salía de la pantalla en celular.

## 4. Qué queda pendiente y por qué (orden recomendado)
1. **Nombre de la persona en «Suprimir» y «Revocar»** (1 h): hoy solo se muestra la cédula. Hace falta consultar el nombre antes de confirmar; no lo hice para no agregar una consulta de datos personales sin revisar qué endpoint y qué permisos usar.
2. **Reabrir evento en Clientes y Calendario** (1 h): usan el mismo desplegable con el texto genérico; son plantillas de otros agentes. Basta cargar `gw-confirm-typed.js` y la misma línea que en `eventos.html`.
3. **Sacar el desplegable de estado de la fila de Eventos** al menú «Más» o a «Editar» (2 h): cambia la disposición de la lista; requiere aprobación visual.
4. **Bloque «Prepara el evento» con ✔ en el menú del evento** (4 h): necesita un endpoint de progreso (`app/`) y `kiosk_select.html`, ambos fuera de mi área.
5. **Rol legible en las demás cabeceras** (1 h): `{{ role_name(staff_role) }}` en ≈30 plantillas (`_kiosk_top.html`, `_crm_shell_top.html`, etc.).
6. **«Para todos» fuera de Apariencia; «Autorizar a todos» para el coordinador; casillas de Usuarios «al instante»; aviso al coordinador temporal al finalizar** (hallazgos 10, 12, 17, 18; 5 h): cambian comportamiento o permisos, no solo textos.
7. **Actualizar los pasos del instalador** (0,5 h): dentro de «Avanzado» sigue citándose `git checkout f5/integracion`, rama que ya no es la de producción. Se conservó literal porque así se pidió; conviene corregirlo o moverlo a `docs/`.
Total estimado: **14,5 h**.

## 5. Qué NO se pudo comprobar
- **Nada se probó con base de datos ni contra staging.** Los flujos reales (suprimir, eliminar cuentas, reembolsar, activar un formulario, crear un evento) no se ejecutaron de punta a punta: se comprobó el código, las pruebas de texto, la lógica en Node y el aspecto en la maqueta.
- **El editor de formularios no tiene maqueta**: la confirmación de «Activo con pago», la línea «Cobra con» y el reembolso se verificaron por sintaxis y por la lógica en Node, no en pantalla dentro del editor (el cuadro de «Activo» sí se vio, abierto desde otra página).
- **La tarjeta de Privacidad no aparece en la maqueta** (el evento ficticio no usa rostro): el cuadro de SUPRIMIR se vio llamándolo directamente; el clic real en los botones no.
- «¿Qué sigue?» se vio ejecutando el código real de `nuevo-evento.js` con un evento ficticio, sin pasar por el asistente completo. Se asume que `POST /api/events` devuelve `id` (el mismo código ya lo usaba para el inventario); si no viniera, se va a la lista como antes.
- El bloque «Cómo publicar el instalador» no se renderiza en la maqueta; su cambio (título del desplegable y una línea) se comprobó por texto.
- Los textos de «qué puede cada rol» salen de `app/auth.py`, `app/main.py` y las plantillas; conviene que Juan David los lea una vez, sobre todo Comercial y Contabilidad.
- No se probó con lector de pantalla.

## 6. Consejo en corto
- **Contrario:** «Escribir una palabra en cinco sitios cansa; si alguien reabre eventos a diario, la va a teclear sin leer. Mide antes de extenderlo más».
- **Primeros principios:** «Lo irreversible debe decir QUÉ se pierde y A QUIÉN; falta el nombre de la persona junto a la cédula».
- **Expansionista:** «El cuadro "¿Qué sigue?" es la semilla del arranque guiado del SaaS: el siguiente paso es marcar ✔ lo ya hecho».
- **Forastero:** «Ahora la cabecera dice "Administrador general" y no una clave rara; pero solo en ocho pantallas».
- **Ejecutor:** «Lo de riesgo Alto quedó cerrado; faltan dos remates de una hora: el nombre en Suprimir y el mismo aviso de reabrir en Clientes y Calendario».

**Veredicto:** las cuatro puertas de riesgo Alto y la de reabrir quedaron con confirmación proporcional, sin tocar datos ni endpoints. **Siguiente paso único:** probar en staging, con un evento de prueba, las cinco confirmaciones escritas y la activación de un formulario con pago.
