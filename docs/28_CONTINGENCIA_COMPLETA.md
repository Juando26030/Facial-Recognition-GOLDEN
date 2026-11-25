# 28 · Registro completo sin conexión (contingencia completa)

Pedido de Juan David (25-nov-2026): si se va el internet un rato, **el registro no debe parar**. Sin conexión se debe poder hacer lo mismo que con conexión: ver todos los datos de la
persona, escribir y guardar, imprimir la escarapela, entregar inventario, ver dependientes y código, y controlar áreas. Encendido por defecto (la auditora ya lo aprobó, según
Juan David). Sin recargar Cloud Run. Rama `feat/contingencia-completa` (sin desplegar; nada en `main`).

## Cómo funciona (tres mecanismos, ninguno pesado para el servidor)

1. **Copia completa cifrada de las personas** (`contingency.js › people*`). Son las MISMAS filas que la pantalla ya bajaba (`/api/users` y sus cambios): ninguna petición nueva. AES-GCM
   256 con la clave no extraíble del equipo, en bloques de 400. Vive y muere con la lista local (cerrar sesión, evento finalizado, sin permiso, 24 h sin refrescar). Sin fotos ni vectores.
2. **Peticiones guardadas** (`outbox.js › enqueueHttp`, `gwFetch`). Lo que la pantalla le habría pedido al servidor (editar, cambiar cédula, estado, firma, eliminar, entrega, entrada a
   una zona, anotar una impresión) se guarda cifrado y, al volver la red, se REPITE en el mismo orden contra **las rutas de siempre**. El servidor aplica sus reglas de en línea; si rechaza
   algo, queda en la «Bandeja» con el motivo para corregirlo. Primero se envían los ingresos (cola de huellas) y después la bandeja.
3. **Service worker** (`kiosk-sw.js`): además del caparazón del Registro guarda el de Áreas e Inventario, la plantilla de la escarapela con sus imágenes, la ventana de impresión y las
   librerías del escáner. Los datos de la persona para la escarapela NUNCA se guardan ahí: sin red se arman al momento desde la copia cifrada.

Única ruta nueva: `GET /api/events/{id}/offline-pack` (dependientes de cada titular y, en el modo «la base lo define», lo asignado a cada persona). Se pide UNA vez al abrir la pantalla;
con `If-None-Match` responde 304. Único cambio en una ruta existente: `POST …/areas/{id}/movement` acepta `client_time` (la hora real de un movimiento hecho sin red, máx. 7 días atrás).

## Qué se puede hacer sin conexión

| Pantalla | Sin conexión |
|---|---|
| Registro · lista | Todas las personas con todos sus datos; buscar por cédula (parcial), nombre o entidad |
| Registro · acreditar | Por lector, cédula escrita, botón de la fila (como antes) |
| Registro · Editar persona | El MISMO modal que con red: todos los campos, dejar un dato vacío, cambiar la cédula (admin), fecha de nacimiento, firmas, estado Registrado / No registrado, eliminar |
| Registro · Registrar nuevo | Todos los campos, fecha de nacimiento, código y firmas (la foto del rostro no: lo biométrico necesita al servidor) |
| Registro · Dependientes | Se ven en «Editar persona» (del paquete guardado) |
| Imprimir escarapela | Botón de la fila e impresión automática, por la ventana de siempre o por USB, con la plantilla de la categoría. Parámetros de impresión INAMOVIBLES sin tocar |
| Control de inventario | Buscar a la persona, entregar (elegido o «lo define la base»), buscar dependientes; existencias y «no repetir» se comprueban en el dispositivo |
| Control de áreas | Entrada/salida por cédula, QR o nombre; alternar automático, «no está adentro» y «sin reingresos» (propio o del grupo) se comprueban en el dispositivo |
| Escáner de cédula | Funciona sin red si ya se abrió una vez con conexión en ese equipo (las librerías quedan guardadas). Definitivo: copia propia (ver Pendientes) |

## Límites (dichos tal cual)

- **Varios equipos sin red a la vez no se ven entre sí**: dos tabletas pueden entregar el mismo último producto o dejar entrar dos veces a alguien en una zona sin reingresos. Al volver la
  red el servidor acepta el primero y el otro queda en la Bandeja con el motivo. Para un evento entero sin internet la herramienta es el servidor local (docs/17).
- **Lo biométrico no funciona sin red** (reconocimiento, captar rostro, foto en la escarapela): necesita al servidor.
- **Impresión compartida** (mandar a la impresora de otro equipo) necesita al servidor: sin red cada equipo imprime en su propia impresora.
- **Reimpresión controlada**: sin red no hay con quién comprobar el conteo; se imprime igual. Si sale por USB queda anotada; si sale por la ventana de impresión, la anotación de esa impresión se pierde (`badge-render.js` es un archivo congelado de la Fase 1.5 y no se tocó).
- **QR «enlace» de la escarapela** (tarjeta pública): sin red no hay enlace; sale el resto de la escarapela.
- **Máximo de entradas por persona** en una zona y los topes por persona del inventario los revisa el servidor al recibir (si no cumple, queda en la Bandeja).
- Las horas de las entregas de inventario y de las ediciones quedan con la hora de envío; la de ingresos y movimientos de zona, con la hora real.
- Los datos que no estaban en el dispositivo antes de caerse la red no aparecen (hay que haber abierto la pantalla con conexión ese día).

## Pendientes

1. **Probar en una tableta real y en staging** (nada de esto se ha probado en un equipo físico): apagar el wifi con el Registro abierto y recorrer la tabla de arriba.
2. **CI**: la ruta `offline-pack`, `client_time` y el cambio del valor por defecto tienen pruebas que solo corren en el CI (aquí no hay base de datos).
3. **Escáner, copia propia**: correr `bash scripts/vendor_cedula_readers.sh` en un equipo con internet y subir `static/vendor/cedula/` (también lo necesita el servidor local).
4. **Texto legal**: el texto C''' de la auditora (política v1.1) dice que el dispositivo guarda solo nombre, categoría, estado y huella. Ahora guarda más. El texto lo cambia la
   auditora, no Claude: pedirle la versión actualizada antes de producción.
5. **Servidor local**: usa el mismo código (contingencia encendida en `deploy/local/.env.local.example`); falta la prueba en el portátil.

## Dónde está el código

- `static/js/contingency.js` (copia completa y copias de lecturas), `static/js/outbox.js` (peticiones guardadas, `gwFetch`), `static/js/offline-data.js` (lecturas con copia y reglas
  puras de áreas e inventario), `static/js/offline-boot.js` + `templates/_offline_boot.html` (arranque en Áreas e Inventario), `static/js/kiosk-sw.js`.
- `static/js/directory.js`, `app.js`, `field-render.js`, `shared-print.js`, `badge-render.js`, `reprint.js`, `areas.js`, `inventario.js`, `inventario-asignado.js`.
- Servidor: `app/offline_pack.py`, `app/offline_pack_core.py`, `app/routers/inv_base.py` (ruta), `app/routers/areas_inventory.py` (`client_time`), `app/routers/badges.py`
  (`offline_print_cfg`), `app/main.py` (interruptor encendido por defecto).
- Pruebas: `tests/js/contingency_full_check.js`, `offline_data_check.js`, `kiosk_sw_print_check.js`, `tests/test_offline_pack_core.py`, `tests/test_inventario_por_base.py` (paquete),
  `tests/test_contingency_flag.py`.
