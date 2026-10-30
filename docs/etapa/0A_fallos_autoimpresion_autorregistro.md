# Fase 0A · Tarea 3 — Autoimpresión y autorregistro: reproducción y causas raíz

Fecha: 2026-10-29/30. Código probado: `origin/main` = `bc4a19d` (contiene todo lo de `b36bf92` más los 6 commits de impresión del 29-oct). **No se cambió nada del código de la app.** Todo dato es ficticio.

## 1. Resumen

1. **Con la pantalla recién abierta y red buena, `main` funciona:** en 108 celdas (3 formas de ingresar × 4 formas de guardar × 3 configuraciones × 3 entornos) **81 FUNCIONAN y 27 FALLAN**. Las 81 que funcionan son todas las de *impresión local* y *compartida con red*, y las de *sin red* con solo autorregistro. Las 27 que fallan son todas **sin red**.
2. **Lo que Juan David vio en el piloto SÍ se reproduce, pero con otra condición, no con otra matriz: la pantalla del digitador se abrió ANTES de que se encendieran los interruptores.** `EVENT_AUTO_PRINT` se escribe en la página una sola vez al cargarla (`templates/kiosk_registro.html:59`) y nunca se refresca; el autorregistro, en cambio, lo decide el servidor en cada petición. Resultado exacto del escenario T1: **se autorregistra y no autoimprime**, con lector, con Enter a mano y al guardar desde «Editar» (escenario T1b); tras recargar la pantalla imprime. Esta es la causa raíz **más probable** de los tres síntomas del piloto (no verificado contra el piloto mismo: no hay registro de cuándo se encendió cada interruptor).
3. Causas adicionales reproducidas: el candado de 30 s se gasta antes de comprobar que se pudo imprimir (T4) y bloquea la reimpresión automática tras «Deshacer» (T5); la ventana de impresión depende de una ventana emergente que se abre tras 1–2 llamadas de red (con red lenta el navegador la bloquea); sin red nunca se autoimprime ni queda pendiente; el autorregistro sin red usa una copia de la bandeja de hasta 4 min (T2).
4. **Defecto nuevo, no pedido:** «Registrar nuevo» sin red (B8 R1) **no se puede usar en `main`**: el botón queda habilitado pero el modal nunca abre (`templates/kiosk_registro.html:379-381`). El camino de la bandeja sí funciona si el modal se fuerza.
5. **Lector, Enter escrito a mano y clic en un resultado no se comportan distinto:** lector y Enter pasan por el mismo manejador (`directory.js:1143`) y el clic por `acreditarFila`; los tres terminan en `fastCheckin`. Las 3 columnas dieron siempre el mismo resultado.

## 2. Método, entorno y límites (qué NO está probado)

- **Entorno:** `uvicorn` local contra una base Postgres local propia (`golden_etapa0a_test`, migrada a `head`), motor facial reemplazado por un doble (como en `tests/conftest.py`), sin correo, `CONTINGENCY_ENABLED=1` como en producción, Chrome 156 manejado con Playwright, un evento «en proceso» ficticio y personas ficticias (cédulas 91000001…). El arnés (no está en el repo; es de un solo uso) hace en cada celda: abre una pantalla nueva, crea la persona, ejecuta el flujo y mide (a) si hay acreditación en la base, (b) cuántas impresiones se pidieron (ventana abierta o trabajo compartido) y (c) la activación de usuario del navegador al abrir la ventana.
- **Definiciones de la matriz:** *lector* = teclas rápidas (3 ms) + Enter; *Enter manual* = teclas lentas (70 ms) + Enter; *clic* = escribir la cédula (filtra la lista) y pulsar el botón de la fila. *Acreditar* = desde el directorio (con autorregistro apagado, tras el escaneo se pulsa «✅ Acreditar» de la fila, que es lo que haría el operador); *Editar* = abrir «Editar», cambiar un dato y «Guardar», con digitador y con coordinador (el modal cambia: el digitador no tiene selector de estado); *Registrar nuevo* = modal «Registrar nuevo» (con lector/Enter se interpreta el escaneo y luego se pulsa «Guardar»: Enter en ese campo no guarda, por diseño). Éxito = registrado en el servidor **y** exactamente 1 impresión si la autoimpresión está activa (0 si no).
- **Entornos:** *con red + impresión local* = impresión compartida apagada, sin impresora USB (ventana de Chrome); *con red + impresión compartida* = el digitador manda a un equipo anfitrión simulado (modo «ventana de Chrome»); *sin red* = contingencia con impresión local. «Con red» e «impresión local» no son ejes independientes en este arnés.
- **Impresión:** `window.open` y `window.print` están sustituidos por registradores: **no salió nada por ninguna impresora**. El camino USB/WebUSB (Brother) y el cuadro de impresión real de Chrome **no se probaron** (ver §6).
- **No probado:** reconocimiento facial (`app.js:119`), QR por cámara, iPad/celular, Windows y su cola de impresión, dos equipos reales, latencia real de un evento (solo una simulada de 2,8 s por llamada), bloqueo real de ventanas emergentes (el arnés mide la activación pero no la bloquea), el piloto mismo.
- Corridas repetidas por defectos del propio arnés (selector que confundía «Editar» con «Acreditar», tope de 12 descargas de la copia local cada 10 min, conteo acumulado de trabajos): se descartaron esos datos y se rehicieron.

## 3. Matriz de resultados

Cada fila agrupa las 3 formas de ingresar porque **dieron siempre el mismo resultado** (lector = Enter manual = clic). 36 filas × 3 = 108 celdas.

| Entorno | Dónde se guarda | Solo autorregistro | Solo autoimpresión | Ambos activos |
|---|---|---|---|---|
| Local con red | Acreditar desde el directorio | FUNCIONA | FUNCIONA | FUNCIONA |
| Local con red | Editar y guardar (digitador) | FUNCIONA | FUNCIONA | FUNCIONA |
| Local con red | Editar y guardar (coordinador) | FUNCIONA | FUNCIONA | FUNCIONA |
| Local con red | Registrar nuevo | FUNCIONA | FUNCIONA | FUNCIONA |
| Compartida con red | Acreditar | FUNCIONA | FUNCIONA | FUNCIONA |
| Compartida con red | Editar (digitador) | FUNCIONA | FUNCIONA | FUNCIONA |
| Compartida con red | Editar (coordinador; sin ruta compartida, imprime en su equipo) | FUNCIONA | FUNCIONA | FUNCIONA |
| Compartida con red | Registrar nuevo | FUNCIONA | FUNCIONA | FUNCIONA |
| Sin red | Acreditar | FUNCIONA (se encola; sincroniza al volver la red) | **FALLA: no imprime** | **FALLA: no imprime** |
| Sin red | Editar (digitador) | FUNCIONA | **FALLA: no imprime** | **FALLA: no imprime** |
| Sin red | Editar (coordinador) | FUNCIONA | **FALLA: no imprime** | **FALLA: no imprime** |
| Sin red | Registrar nuevo | **FALLA: el modal no abre** | **FALLA: el modal no abre** | **FALLA: el modal no abre** |

Notas de la matriz:
- «Sin red / FALLA: no imprime»: la persona sí queda registrada (en la cola local; el estado en pantalla dice «Registrado»), pero **no se pide ninguna impresión**, ni sin red ni al volver la red. Diseño actual: ninguno de los caminos sin red llama a `maybeAutoPrint` (ver §4). 2 de las 18 celdas «sin red con autoimpresión» (Editar, Enter manual, autoimpresión; digitador y coordinador) aparecían sin llegar al servidor: **investigado el 30-oct, era un problema de la prueba (tiempo), no pérdida de datos** (§9.1). Mi comprobación de «minutos después» de la primera entrega era inválida (§9.1) y queda retirada.
- «Sin red / Registrar nuevo / FALLA: el modal no abre»: ver §5-F. 9/9 celdas.
- Con **latencia simulada de 2,8 s por llamada** se repitieron 5 celdas con ambos interruptores activos y lector: todas registraron y pidieron 1 impresión, pero **en 2 de las 4 aperturas de ventana medidas el navegador ya no tenía activación de usuario** (`userActivation.isActive = false`): con las ventanas emergentes bloqueadas (valor por defecto de Chrome) esas dos impresiones se habrían perdido en silencio. En red de laboratorio siempre fue `true`.
- Facial, USB y dispositivos físicos: **NO SE PUDO PROBAR** (ver §2 y §6).

## 4. Flujo de código de cada camino

| Camino | Qué se ejecuta (archivo · función · línea en `main`) |
|---|---|
| Escribir/escanear en «Buscar por cédula» + Enter (lector y manual) | `static/js/directory.js:1143` manejador `keydown` → `fastCheckin` (`:1036`) → `postWithRetry` → `POST /api/checkin-cedula` (`app/routers/api.py:731`; acredita solo si `event.auto_register`, `:650`/`:793`; si no, responde `FOUND_PENDING`) → con `result === 'SÍ'`: `BadgePrint.maybeAutoPrint(id)` (`directory.js:1087`) |
| Autorregistro apagado: botón de la fila tras el escaneo | `directory.js:1101-1111` (botón `.btn-accredit-pending`) → `fastCheckin(..., confirm=true)` → mismo `SÍ` → `maybeAutoPrint` |
| Clic en «✅ Acreditar» de una fila | `directory.js:977` `acreditarFila` → `fastCheckin(..., confirm=true)`; ofrece «Deshacer» (`offerUndo`, `undoAccredit` → `POST /api/events/{id}/accreditations/undo`, `api.py:825`, 15 s) |
| Editar y guardar — coordinador | `directory.js:317` guardar → `PATCH /api/users/{id}` (`api.py:1168`) → `applyStatus` (`:368`): si el selector pasó a «Registrado» → `PATCH /api/events/{id}/users/{id}/status` (`api.py:1404`) → `maybeAutoPrint` (`:394`) |
| Editar y guardar — digitador (sin selector de estado) | mismo guardado → `directory.js:439-447`: si la persona no estaba registrada, `PATCH …/status` → `maybeAutoPrint` (`:444`) |
| Registrar nuevo | `static/js/app.js:448` `regForm.onsubmit` → `submitManualRegister` (`:404`) → `POST /api/register` (`api.py:1454`) → `maybeAutoPrint` (`app.js:441`) |
| Escáner facial / «Imprimir escarapela» tras el escaneo | `app.js:115` `offerPrint` → `maybeAutoPrint` (`:119`) (no probado) |
| **Decisión de imprimir** | `window.EVENT_AUTO_PRINT` (`kiosk_registro.html:59`, **fijo al cargar la página**; el switch del coordinador, `:433-447`, solo cambia esa variable en SU pantalla) |
| Despacho de la impresión | `shared-print.js:570` `maybeAutoPrint` → `printFor(auto=true)` (`:532`): compartida apagada y sin USB → `badge-render.js:374` `maybeAutoPrint` → `claim` (`:348`, candado de 30 s en memoria y Web Locks) → `printNow` (`:369`: `POST print-log`, y **después** `window.open`, `:284`); compartida encendida → `claim` → `registeredOrSay` (`:518`, `GET /api/events/{id}/print-check/{uid}`, `shared_print.py:261`) → ruta `shared`: `POST /api/events/{id}/print-jobs` (`shared_print.py:211`, deduplica 30 s) o ruta propia: `printNow`/USB |
| Sin red (contingencia) — acreditar | `directory.js:1039` `GC.active()` → `offlineCheckin` (`:1018`) → si `GC.autoRegister()` (`contingency.js:257`, bandera **copiada de la última descarga**, cada 4 min `REFRESH_MS`, `:14`) → `offlineAccredit` (`:126`) → `GC.enqueue`; **no llama a `maybeAutoPrint`** |
| Sin red — editar | `directory.js:185` → `buildOfflineEditModal` (solo estado de registro) → `offlineAccredit`; **sin impresión** |
| Sin red — registrar nuevo | `kiosk_registro.html:378` `openRegisterModal` **se niega** si hay contingencia; si el modal se abre, `app.js:491` `queueOffline` → bandeja (`outbox.js`); **sin impresión** |

## 5. Causas raíz, con evidencia

**A. La autoimpresión se decide con un valor congelado al cargar la página (CAUSA PRINCIPAL DEL PILOTO).** `EVENT_AUTO_PRINT` lo escribe la plantilla al renderizar (`kiosk_registro.html:59`) y `maybeAutoPrint` solo mira esa variable (`badge-render.js:375`, `shared-print.js:570`). El autorregistro, en cambio, lo evalúa el servidor en cada petición (`api.py:650`, `:793`). Si el coordinador enciende los interruptores con las pantallas de los digitadores ya abiertas, estas registran solas pero no imprimen.
*Evidencia (escenario T1):* pantalla del digitador abierta con ambos interruptores apagados; el coordinador los enciende (PATCH 200, servidor `auto_print_badge = true`, `auto_register = true`); el digitador escanea con lector: **registrado = 1, impresiones = 0, `EVENT_AUTO_PRINT` en pantalla = false**. Tras recargar: escanea otra persona → registrado = 1, impresiones = 1. *T1b:* igual guardando desde «Editar»: registrado = 1, impresiones = 0. Esto explica a la vez «fallaba con lector y con Enter», «fallaba al guardar desde Editar» y «se autorregistraba pero no autoimprimía».
*Lo que NO reproduje:* un fallo con ambos interruptores encendidos antes de abrir la pantalla (funciona en las 81 celdas). No sé si la versión que corrió el piloto tenía además otro defecto.

**B. El candado de 30 s se gasta antes de saber si se pudo imprimir.** En `printFor` el `claim` va antes de `registeredOrSay` (`shared-print.js:534` y `:536`). Si la comprobación falla (red intermitente), el aviso dice «reintenta», pero cualquier reintento automático de la misma persona queda bloqueado en silencio durante 30 s.
*Evidencia (T4, compartida):* se hicieron fallar las dos consultas de `print-check` de la primera llamada; la persona quedó registrada, trabajos = 0, aviso «⚠️ Sin conexión: no se pudo comprobar… reintenta»; una segunda llamada automática a los pocos segundos **no hizo ninguna consulta nueva** (llamadas a `print-check` = 2) y no creó trabajo.
**Variante (T5):** acreditar → «Deshacer» → volver a acreditar a la misma persona dentro de 30 s: la persona queda registrada y **no se vuelve a imprimir** (impresiones totales = 1, registrado final = 1).

**C. La ventana de impresión se abre tras llamadas de red: depende de la activación de usuario.** `printNow` hace `await logPrint(...)` (una llamada) antes de `window.open` (`badge-render.js:369-373`); en compartida además va antes `print-check`. Chrome solo permite abrir una ventana emergente durante ~5 s desde el último gesto.
*Evidencia:* con 2,8 s de latencia por llamada, en 2 de las 4 aperturas medidas `userActivation.isActive` ya era `false`. **No verificado en un Chrome real con las ventanas emergentes bloqueadas** (el arnés no las bloquea) ni cómo estaba configurado Chrome en el piloto.

**D. Sin red no hay autoimpresión ni cola de impresión pendiente.** Ningún camino de contingencia llama a `maybeAutoPrint` (ver §4); al volver la red tampoco se imprime lo acreditado sin red (verificado: 0 aperturas tras sincronizar). La impresión compartida exige red por diseño (`registeredOrSay`); la ventana local tampoco funcionaría tal cual, porque `badge_print.html` la renderiza el servidor.

**E. El autorregistro sin red usa una copia de la bandera de hasta 4 minutos.** `GC.autoRegister()` lee la bandera guardada en IndexedDB con la última descarga de la copia local (`contingency.js:257`, refresco cada 4 min).
*Evidencia (T2):* la copia se descargó con el autorregistro apagado; se encendió en el servidor; al cortar la red, la bandera local = **false** y la del servidor = true (el escaneo sin red solo resaltaría a la persona en vez de acreditarla).

**F. «Registrar nuevo» sin red está inaccesible en `main` (defecto, no pedido).** La rebanada B8 R1 (commit `7647ebc`) cambió el habilitado del botón (`kiosk_registro.html:471`, título «la persona se guarda en este dispositivo…») pero dejó el viejo guardia de `openRegisterModal` (`kiosk_registro.html:379-381`, del commit `f806aa2`), que devuelve «Sin conexión: no se pueden registrar personas nuevas».
*Evidencia:* en Chrome sin red, con la bandeja lista (`GoldenOutbox.instance.supported = true`) el botón está habilitado (`disabled = false`) y al pulsarlo `registerModal` sigue en `display: none`. Si el modal se fuerza abierto, la persona se guarda («✓ Guardado en este dispositivo. Se enviará solo al volver la red»), llega al servidor al volver la red (registrado = 1) y **no se imprime** (0 aperturas, ni sin red ni tras sincronizar), aun con ambos interruptores activos. `tests/js/outbox_check.js` y `tests/test_outbox_sync.py` no pasan por el modal, por eso no lo detectan.

**Observación (carrera secundaria, no confirmada):** si se corta la red a los pocos segundos de cargar la pantalla, antes de que arranque la bandeja de salida, `onChange` (`kiosk_registro.html:470`) deja el botón deshabilitado y nada lo vuelve a habilitar; lo observé en el arnés con 2,5 s de espera, no con 5–7 s.

## 6. Pruebas físicas para Juan David (requieren la Brother o dispositivos reales)

Estas combinaciones **no se pudieron probar** aquí. «Hoy» = lo que predice el código actual; «después del arreglo» = lo esperado.

1. **Causa A con impresora real (la más importante, 10 min).** Dos equipos con Chrome normal (nunca `--kiosk-printing`): el del digitador y el del coordinador. (a) En el del digitador abre el Registro **con los dos interruptores apagados**. (b) En el del coordinador enciende «Modo autoregistro» y «Auto-impresión». (c) En el del digitador, **sin recargar**, escanea con el lector una cédula de prueba. Hoy: queda «Registrado» y no sale escarapela. (d) Recarga el equipo del digitador y escanea otra cédula: debe imprimir. Repite el paso (c) guardando desde «Editar».
2. **USB directo (Brother conectada al equipo que atiende):** «Conectar impresora» → la barra debe decir «Impresora conectada» → escanear con ambos interruptores activos → una etiqueta. Si falla, anota el texto exacto de la barra y del aviso. Aquí se ejercita `printUsb`, que este arnés no tocó.
3. **Compartida con equipo anfitrión real:** el anfitrión con la Brother (USB) o con «Este equipo imprime con la ventana de Chrome»; el digitador escanea → debe aparecer «Impreso en <anfitrión>» o el aviso de cola. Repite con la red del celular lenta (modo 3G de las herramientas del navegador o un punto de acceso saturado).
4. **Ventanas emergentes (causa C):** en el equipo que imprime con la ventana de Chrome, deja el valor por defecto de «Ventanas emergentes y redirecciones» (bloqueadas) y limita la red a «3G lento»; escanea con ambos interruptores. Si no sale ventana, aparece el icono de bloqueo en la barra de direcciones. Anota la latencia aproximada.
5. **Candado de 30 s (causas B y T5):** acredita a una persona, pulsa «Deshacer» y vuelve a acreditarla de inmediato: hoy no imprime (debe esperar 30 s y usar «Imprimir escarapela»).
6. **Sin red real (modo avión):** abre el Registro con red, espera 10 s, activa modo avión, escanea una cédula con ambos interruptores y mira la franja «Modo contingencia». Hoy: se acredita, no imprime; al volver la red sincroniza y tampoco imprime. Prueba también «Registrar nuevo» (hoy no abre el modal).

## 7. Arreglo propuesto (NO implementado)

Preferir lo que pidió el plan: **una sola cola de acciones por persona** antes que parchar cada caso. En dos tiempos:

**Mínimo (1–2 días; ataca A, B y la parte «imprimir» de C):**
1. Que **el servidor diga si se imprime**: `POST /api/checkin-cedula`, `/api/register`, `PATCH …/status` y `…/accreditations/undo` devuelven `auto_print` (leído de `Event.auto_print_badge` en esa petición) y el cliente imprime según esa respuesta, no según `window.EVENT_AUTO_PRINT`. El latido de impresión (cada 10 s, ya existe) también devuelve las banderas para que el interruptor de cada pantalla se actualice sin recargar. Con eso desaparece la causa A.
2. El `claim` se confirma **después** de comprobar y de pedir la impresión (o dura 3–5 s si falló) y se libera con «Deshacer» (causas B y T5).
3. Abrir la ventana de impresión **en el gesto del usuario** (al inicio del flujo, antes de cualquier `await`) y navegarla después; o usar un iframe oculto: elimina C.

**Estructural (3–5 días; incluye D, E y F):** una cola persistente en IndexedDB (ya existen la de contingencia y la bandeja) con una entrada por persona y evento y pasos ordenados `registrar → comprobar → imprimir`, un único ejecutor, estados *pendiente / en curso / hecho / falló con motivo* y reintento con el mismo `client_id` (ya idempotente). Funciona con y sin red: «imprimir» queda pendiente y sale al sincronizar o con «Imprimir pendientes». Reemplaza las 5 llamadas dispersas a `maybeAutoPrint` (`directory.js:394,444,1087`, `app.js:119,441`), da el estado visible por persona que pide la Fase 1B y obliga a decidir qué hace el camino sin red. Además: corregir `openRegisterModal` (F) y refrescar `autoRegister` de la copia local al recibir el latido (E).

**Pruebas que deja:** convertir este arnés en prueba automatizada (Playwright contra una base de pruebas) que corra la matriz de §3, más los escenarios T1, T2, T4 y T5, antes de cada despliegue a staging. Hoy ninguna prueba cubre «pantalla abierta antes de encender el interruptor».

## 8. Dudas (primera entrega; respondidas el 30-oct en §9.2)

- ¿Qué versión corrió el piloto y a qué hora se encendieron los interruptores respecto de la apertura de las pantallas de los digitadores? Con eso se confirmaría A como causa del piloto.
- ¿Los equipos del piloto tenían las ventanas emergentes permitidas para el sitio?
- ¿Sin red debe imprimirse (cuando la impresora es local) o basta con dejar la impresión pendiente? Define el alcance de D.

## 9. Seguimiento del 30-oct (solo lectura; nada se corrigió)

### 9.1 Las 2 celdas sin red que «no llegaron al servidor»

**Veredicto: problema de la prueba (tiempo de espera), NO pérdida de datos. Llegan solos a los pocos segundos.**

- **Qué eran:** *sin red · Editar · Enter manual · solo autoimpresión*, con digitador (persona 91000014) y con coordinador (91000023). En la primera corrida la persona quedó «Registrado» en pantalla y en la cola local («1 en cola»), pero a los ~9,5 s de volver la red aún no había ninguna petición de sincronización (`reqs_tras_volver_red` vacío) y el arnés cerró la pantalla y leyó la base.
- **Causa:** la sincronización no arranca al instante de volver la red: la contingencia solo sale a «normal» tras 2 sondas buenas de `/health` seguidas (cada 5 s) más una petición autenticada (`contingency.js:14`, `:274`), así que el envío sale entre ~5 y ~10 s después. Esas dos celdas cayeron justo del lado de los 9,5 s del arnés.
- **Evidencia (reproducción aislada, mismo flujo, digitador y coordinador, `probe_sync.py` de uso único):** cola = 1 y servidor = 0 a los 5 s; **cola = 0 y servidor = 1 a los 9,5 s**; una sola petición `POST /api/events/1/access-logs/sync` → 200; sin duplicados (servidor = 1 a los 20, 35 y 60 s).
- **Corrección de mi primera entrega:** escribí que a esas celdas «en servidor ahora: 0». Esa lectura no valía nada: los guiones que corrieron después (escenarios y latencia) vacían la base de pruebas al empezar, así que cualquier lectura posterior daba 0. Debí verificarlo antes de afirmarlo; por eso el reporte decía «no determinado».
- **¿Hay riesgo de pérdida de datos sin red? No observé ninguno en este flujo.** Pruebas: (a) cerrar la pantalla con la cola pendiente (cola = 1, antes de que la bandeja vuelva a «normal»): una pantalla nueva del mismo equipo la sincroniza (cola = 0, servidor = 1, sin duplicado); (b) cierre en pleno vuelo de la petición: **no logré provocarlo** (la petición terminó antes de cerrar); lo cubre por diseño el reenvío idempotente por `client_id` (`replayed`, `tests/test_contingency_sync.py:36` y `:97`), no por mi prueba. Riesgos que SÍ existen y ya estaban documentados (no los probé): lo no sincronizado a los **7 días se elimina** del dispositivo con aviso desde el día 3 (`contingency.js` `pruneOld`); si el navegador borra los datos del sitio (modo privado, iOS tras ~7 días sin uso, «borrar datos») se pierde la cola; el cierre de sesión avisa de lo pendiente pero no lo borra. La **autoimpresión sin red sí se pierde hoy** (D): la persona queda registrada pero no queda nada pendiente de imprimir.

### 9.2 Respuestas de Juan David (30-oct) y su efecto

| Tema | Respuesta | Efecto en este reporte |
|---|---|---|
| Versión del piloto | Corrió en staging con `b36bf92` y luego se exportó a producción. Producción corre hoy `bc4a19d` (confirmado en `/sistema`), igual que `main`. Producción solo tiene datos reales y staging solo de prueba. | `b36bf92` ya contenía el defecto A (`EVENT_AUTO_PRINT` fijo al cargar; no cambió en los 6 commits posteriores). Pruebas siempre en staging o local con datos ficticios. |
| Cuándo se encendieron los interruptores | No se sabe. | La causa A sigue siendo la hipótesis más probable, **no confirmada**. |
| Ventanas emergentes | Chrome pide permiso la primera vez; hasta donde se sabe no estaban bloqueadas. | Causa C: **poco probable en el piloto**; se conserva como riesgo (§9.3). |
| Sin red | Con impresora local (USB o ventana de Chrome): imprimir igual. Si depende de otro equipo (compartida) o no hay impresora: dejar **pendiente en una cola visible, nunca perderlo, y sincronizar al volver la red.** | Requisito para el arreglo (§9.4). |
| VM antigua | Todavía no está cerrada: no borrar nada de `deploy/`, solo marcarlo como heredado. | Marcado en `0A_pendientes_docs_15_y_16.md` (sección D); no se tocó `deploy/`. |

### 9.3 Flujos que abren una ventana DESPUÉS de una llamada de red (riesgo del navegador)

`window.open` solo está permitido ~5 s después del último gesto del usuario (clic o tecla). Estos caminos lo llaman tras una o más llamadas de red (medido: 2 de 4 aperturas con 2,8 s por llamada ya sin activación):

| Flujo | Llamadas de red antes de abrir la ventana | Dónde |
|---|---|---|
| Autoimpresión local tras escanear/Enter/clic en «Acreditar» | 1) `POST /api/checkin-cedula` 2) `POST …/print-log` | `directory.js:1087` → `badge-render.js:369` `printNow` → `openPrintTab` (`:284`) |
| Autoimpresión local tras «Editar → Guardar» (coordinador) | `PATCH /users/{id}`, `PATCH …/status`, `POST print-log` (3) | `directory.js:317-394` |
| Autoimpresión local tras «Editar → Guardar» (digitador) | `PATCH /users/{id}`, `PATCH …/status`, `POST print-log` (3) | `directory.js:439-444` |
| Autoimpresión local tras «Registrar nuevo» | `POST /api/register` (+ firmas), `POST print-log` | `app.js:432-441` |
| Autoimpresión con compartida encendida y ruta propia (sin USB) | + `GET print-check` antes del `print-log` (3-4) | `shared-print.js:532-566` |
| Botón manual «Imprimir escarapela» (local) | `GET print-count`, [confirmación «¿imprimir de nuevo?» si ya se imprimió: el tiempo humano cuenta], `POST print-log` | `badge-render.js:304-326` `openNow` |
| Botón manual con compartida y ruta propia | + `GET print-check` | `shared-print.js:532-566` |
| Reimprimir desde la Cola (ruta propia) | consultas previas + `print-log` | `shared-print.js` (`reprint`) |
| «Imprimir pendientes» del anfitrión | los trabajos ya vienen reclamados; abre desde el clic del botón, pero reclama (`print-jobs-next`) antes de abrir | `shared-print.js` (no revisé el orden exacto: **no verificado**) |
| USB directo | no abre ventana | — |
| Ruta compartida del que pide | no abre ventana (crea un trabajo) | — |

La corrección barata es abrir la ventana al inicio del flujo, dentro del gesto, y navegarla al terminar (§7).

### 9.4 Ajuste a la propuesta de arreglo por lo decidido para «sin red»

La cola de acciones por persona (§7, «Estructural») debe cumplir:
1. **Equipo con impresora local** (USB directo o ventana de Chrome): sin red se imprime igual, sin esperar la comprobación del servidor. Hay que resolver dos cosas que hoy lo impiden: la página `badge_print.html` la renderiza el servidor (no está en la copia local; se necesita una versión que se dibuje en el navegador, como ya hace el camino USB con `BadgeRender`) y `registeredOrSay`/`print-check` pregunta al servidor (sin red se usa el estado de la copia local).
2. **Impresión compartida (depende de otro equipo) o equipo sin impresora:** la acción «imprimir» queda **pendiente en una cola visible** (franja con contador y lista por persona: «pendiente · motivo»), persistente en IndexedDB, nunca se descarta en silencio, y se envía sola al volver la red; si sigue sin impresora, queda en la lista para «Imprimir pendientes».
3. Estados visibles por persona: *Registrado · Imprimiendo / Impreso / Pendiente (sin red, sin impresora, anfitrión desconectado) / Falló: motivo.*
4. Caducidad: la misma de la bandeja (7 días, con avisos desde el día 3) y nunca borrar sin avisar.

### 9.5 Dudas que siguen abiertas
- La lista original de los 41 puntos **no llegó** (ver `0A_estado_41_puntos.md`): hay que reenviarla para corregir la numeración.
- Cuándo se encendieron los interruptores en el piloto (no hay registro; ayudaría la fecha de modificación del evento en staging, si existe).
