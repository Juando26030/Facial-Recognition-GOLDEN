# Evento compartido entre varios servidores locales, con la nube como puente (20-nov-2026)

**Estado: EN PRODUCCIÓN desde el 21-nov-2026** (commit `4615fb4`, migración `0160_shared_local_events`, paquete de actualización de los servidores locales `2026.11.21.222212`). Rama de trabajo: `feat/evento-compartido-nube`. Se probó antes en staging (mismo commit). Pedido de Juan David el 20-nov-2026.

**Lo que ya funciona hoy:** «Usará servidores locales» → «Conectados con puente por la nube». **Lo que NO existe todavía:** «Un servidor se conecta a otro» y «Un tercer servidor hace de puente» (sin internet): salen en pantalla como «(próximamente)» y no se pueden elegir. Para usar la forma por la nube, cada servidor local debe actualizarse a la versión nueva.

## 1. El problema
Eventos grandes con dos (o más) entradas lejos entre sí: un solo servidor local no alcanza (los routers se ponen lentos con más de ~6 equipos y no se puede tender cable entre
entradas). Con un servidor por entrada, cada uno tenía su propia base: alguien registrado en la entrada A no aparecía como «ya registrado» en la entrada B.

## 2. La solución elegida (camino «nube como puente»)
Cada entrada lleva su servidor local **con internet** (red del lugar, celular o Starlink). El evento se marca **«Compartido entre varios servidores locales»** en la nube y se descarga en
cada servidor. Mientras el evento esté «En proceso», cada servidor, cada `NODE_SHARED_SECONDS` (15 s por defecto):
1. **Sube** lo suyo, igual que siempre (personas nuevas, registros, impresiones, cambios: `app/node_sync.py`).
2. **Baja** lo que hicieron los demás desde su cursor (`GET /api/node/events/{id}/changes`) y lo aplica sin duplicar (`app/peer_changes.py`).

Así, en la entrada B se ve en segundos lo que registró la A. **Sin internet, cada entrada sigue trabajando sola** y se pone al día cuando vuelve la conexión (reintento cada minuto).

Las opciones sin internet (enlace de radio punto a punto, un servidor con varios puntos de acceso, sincronización directa entre servidores por la red local) quedan **en pausa**.

## 3. Cómo funciona
### Nube
- **«Usará servidores locales»** (21-nov-2026): en Editar evento › Servidor local se enciende esa opción y se elige UNA forma de conectarlos (2 o más servidores en los tres casos):
  «Conectados con puente por la nube» (`cloud`, lo de este documento), «Un servidor se conecta a otro» (`peer`) y «Un tercer servidor hace de puente» (`hub`). Las dos últimas (sin internet)
  aparecen como «próximamente» y la nube las rechaza (409). Queda en `events.local_mode`; `POST /api/events/{id}/lease/mode {"mode": ""|"cloud"|"peer"|"hub"}` (el viejo `/lease/shared` sigue).
- `events.local_shared`: el evento acepta varios servidores (lo enciende el modo `cloud`). Lo cambia cualquiera que pueda llevar eventos a local. Apagarlo solo con uno o ningún servidor.
- `event_local_nodes`: qué servidores tienen el evento. El primero sigue en `events.local_node_name` (el «principal»), así todo lo que ya leía esa columna sigue igual.
- `event_lease.is_writer` reemplaza la comparación «¿es el servidor que lo tiene?» en todos los puntos donde un servidor escribe o baja datos (paquete, checklist, subidas, liberar).
- **Pasar a internet** desde un servidor: sale solo ese servidor; el evento vuelve a la nube cuando sale el último. Si salió el principal, el siguiente pasa a serlo.
- `/api/node/ping` devuelve `shared_events`: un servidor que ya tenía el evento se entera en su ciclo normal (≤ 30 min, o «Sincronizar») de que ahora es compartido. **Lo recomendado es marcarlo antes de descargarlo.**
- `/api/node/events/{id}/changes`: un cursor por sección (`peer_changes.KEYS`: `l` registros, `a` personas, `p` impresiones, `c` cambios, `e` ediciones, `m` áreas, `d` entregas, `t` turnos, `q` llamados, `r` ruleta, `x` contactos); devuelve lo que tiene id mayor, en páginas de 500. Solo para servidores del grupo.

### Servidor local
- Al descargar (o sumarse), guarda el cursor que le dio la nube **antes** de exportar el paquete: lo que caiga entre medio se repite y no duplica.
- Lo bajado queda con `from_peer = true` y la subida nunca lo devuelve (`_persons_query`, `_logs_query`, etc. lo excluyen).
- En un evento compartido, los identificadores que sube llevan el **prefijo propio del servidor** (`peer_changes.node_tag`, sale de `INSTALLATION_ID`). Sin eso, dos servidores con el mismo id de evento
  local generarían el mismo `op_id`/`client_id` y la nube tomaría el segundo como repetido (se perdería).
- Reglas al aplicar: persona que ya está en el evento → no se pisan sus datos; registro con un `client_id` que ya existe o con el prefijo propio → se salta; un «Nuevo» de alguien que ya tiene su alta aquí → se salta;
  impresiones y cambios → por llave natural (persona + momento + tipo).
- Pantallas: en «Eventos de la nube» del servidor, un evento compartido que ya está en otro servidor muestra **«Sumarse (compartido)»**; en Sincronización se ve «Compartido» y la hora de la última bajada.

## 3b. Lo que antes se quedaba en el servidor local y ahora SUBE (modo normal y compartido)
Pedido de Juan David el 20-nov-2026: «eso también debería subirse a la nube». Desde 0160, en **todo** servidor local (compartido o no):
| Qué | Cómo sube | En la nube | En los otros servidores (compartido) |
|---|---|---|---|
| Ediciones de datos de la persona (`person_change_log`) | `/extra` › `edits` | se aplica el valor; gana el cambio más reciente de cada campo | igual |
| Deshacer registro («No registrado») | `/records` (como antes) | **ahora se aplica**: borra los registros de la persona hechos hasta ese momento | igual |
| Fecha de nacimiento | `/records` | **ahora se aplica** (y con ella si puede tener biometría) | igual |
| Movimientos de áreas | `/extra` › `areas` (el área por su nombre) | se guardan | igual |
| Entregas de inventario | `/extra` › `deliveries` (ítem y categoría madre por nombre) | se guardan | igual |
| Turnos y llamados | `/extra` › `turns`, `calls`, `turn_status` | se guardan; el estado solo avanza | turnos nuevos y llamados |
| Sorteos de la ruleta | `/extra` › `roulette` | se guardan | igual |
| Contactos de expositores | `/extra` › `leads` (el expositor por su nombre; si no existe en la nube se crea) | se guardan | igual |
| Aceptaciones / firmas | `/extra` › `acceptances` | se crean o se verifican (la verificación más antigua vale) | no (van a la nube) |
| Autorizaciones de datos (Ley 1581) | `/extra` › `consents` (por id; la huella de la cédula se recalcula en la nube) | solo INSERT, como exige la tabla | no (van a la nube) |

**Límites de lo que la nube acepta de un servidor (seguridad, 22-nov-2026):**
- **Solo asistentes del evento.** Las ediciones de datos, la fecha de nacimiento, las aceptaciones y las autorizaciones solo se aplican a personas que están en `event_attendees` de ESE
  evento (antes bastaba con ser del mismo cliente). Lo demás no se guarda y se cuenta en `rejected` (en la respuesta de `/extra` y `/records`, y en un aviso del log sin datos
  personales); la respuesta sigue siendo `ok: true` para que el ciclo del servidor no se trabe. El orden de subida ya garantiza el caso normal: las personas nuevas suben primero
  (`/outbox`) y quedan como asistentes. Al BAJAR lo de otros servidores (`from_peer=True`) no se filtra: la fuente es la nube.
- **Aceptación biométrica que llega de un servidor = por verificar.** Si un servidor sube una autorización con `accepted` para alguien que no tenía una vigente en la nube y sin la
  verificación del personal (`acceptances` con `verified_at`), queda con la misma marca de `/aceptar` (`web_acceptances` sin `verified_at`): la persona no entra a la matriz de
  reconocimiento hasta que el personal confirme su identidad (`POST /api/events/{id}/web-acceptance/{cédula}/verify`). El registro en `audit_consent_logs` se guarda igual (solo INSERT).
- **Servidor con cliente fijo (0163).** Si su llave se creó con «Solo eventos del cliente…», tampoco puede sumarse a un evento compartido de otro cliente (404). Ver docs/17 § Llaves.
- Un servidor con esquema anterior a 0163 sigue recibiendo 409 «desactualizado» al subir hasta actualizarse (regla de siempre, `node_auth.require_compatible`); sus llamadas y las
  respuestas no cambiaron de forma (solo se agregó `rejected`).

Cada tipo tiene su marca de agua en el evento local (`sync_edit_id`, `sync_area_id`, `sync_delivery_id`, `sync_turn_id`, `sync_call_id`, `sync_turn_at`) y cuenta en «pendientes»: «Pasar a internet»
no libera mientras falte algo. Todo eso salió de la lista de «solo local» que bloqueaba la liberación; en ella queda únicamente el inventario de ALMACÉN del evento (en el servidor local es de
solo consulta: no hay catálogo de productos), que de todas formas va en la copia completa.

## 3c. Copia completa del evento en la nube (seguro contra la pérdida del servidor)
Pedido de Juan David: «nada debe quedar en el local». Además de la fusión fila por fila, en cada ciclo largo (30 min), en «Sincronizar» y antes de «Pasar a internet» el servidor sube una
**copia completa** del evento (`app/local_backup.py`): TODAS las tablas con `event_id` (se descubren solas: una tabla nueva entra sin tocar código), las de los formularios del evento y las
personas (sin rostro), más los **archivos** que esas filas nombran (documentos, evidencias…), cada uno una vez. Solo sube si cambió (huella SHA-256). La nube guarda las últimas 20 copias por
servidor en el almacenamiento privado y solo un **super_admin** las ve y descarga (Editar evento › Servidor local › «Copias completas…»). No se fusionan solas: son el respaldo para recuperar
cualquier cosa que la fusión no cubra (por ejemplo cambios de configuración del evento hechos en el servidor local).

## 4. Conflictos y límites (primera versión)
- **Misma persona en las dos entradas durante un corte:** quedan los dos registros (como en el modo sin red de los quioscos); la nube los conserva y se ven en el historial. La regla de negocio de cada evento decide qué hacer.
- **Misma persona dada de alta en las dos entradas:** gana la primera alta que llegó a la nube; la segunda queda como registro de una persona existente.
- **Turnos en eventos compartidos:** cada entrada debe usar **sus propias filas (letras)**; si dos servidores dan el mismo número de la misma fila a personas distintas, el segundo se omite
  (queda contado como conflicto). Los otros servidores reciben los turnos nuevos y los llamados; «atendido/saltado» sube a la nube pero no se reparte a los demás servidores.
- **Configuración del evento hecha en el servidor local** (parámetros, campos, plantilla de escarapela, áreas o ítems nuevos): queda en la copia completa, pero NO se fusiona sola en la nube.
  Un movimiento de un área o una entrega de un ítem que solo existe en el servidor se omite en la fusión (queda en la copia). Recomendación: configurar el evento en la nube antes de bajarlo.
- **Rostros/biometría:** el servidor local no hace reconocimiento facial; no hay nada que subir.
- **Estado del evento:** cada servidor pone su copia «En proceso» como siempre; la sincronización rápida solo corre en ese estado.

## 5. Costo
Por servidor: 1 subida (solo si hay algo nuevo) + 1 consulta de cambios cada 15 s ≈ 240 peticiones/hora, unos pocos KB cada una. En Cloud Run es del orden de centavos de dólar por evento.
Lo que más pesa es que la base (Neon) no se duerme mientras el evento compartido está «En proceso» con internet (≈ 0,25 CU por hora). Fuera de «En proceso» no se consulta la nube más de lo normal.
`NODE_SHARED_SECONDS` sube el intervalo si se quiere gastar menos (con más demora en verse).

## 6. Pruebas
`tests/test_evento_compartido.py`: un solo escritor si no es compartido; dos servidores en un evento compartido se ven por `/changes`; salen uno a uno; no se deja de compartir con dos dentro;
el ping avisa; aplicar lo bajado es idempotente, salta el eco propio y no pisa datos; el ciclo corto sube con prefijo propio, baja y nunca devuelve lo bajado.

## 7. Pendiente (ya está en producción; esto es lo que falta comprobar y construir)
0. Construir las dos formas sin internet (`peer` y `hub`); la pantalla y `events.local_mode` ya las tienen reservadas.
1. Ensayo real con dos servidores locales y dos redes distintas (por ejemplo una con Starlink), registrando a la vez en las dos entradas, cortando internet en una y volviendo.
2. Medir la demora real entre entradas y el consumo de datos (para el plan de Starlink).
3. Decidir si en eventos compartidos se avisa en el quiosco «registrado en la otra entrada a las …» (hoy se ve como un registro más).

## 8. Lo que salió a producción el 21-nov-2026 junto con esto
- **Hotfix del formulario público del evento 14 («Error de red al subir el archivo» en celulares):** `static/js/direct-upload.js` copia el archivo a memoria al elegirlo (en Android un PDF de Drive/WhatsApp puede dejar de poderse leer) y reintenta 4 veces con una URL firmada nueva. Mismo flujo y mismos textos; su huella está renovada en `tests/test_publico_congelado.py`.
- **Pruebas automáticas en verde por primera vez en semanas** (4.570 pasan, 0 fallan): 47 pruebas viejas se pusieron al día; las que mostraron errores reales se arreglaron en la app (imprimir a alguien de otro evento ya no revela su nombre; la consulta de categoría respeta la base archivada; preimpresiones sin script en línea; ícono en las etiquetas QR; mensaje al eliminar un producto con objetos con serial).
- La CI sale en verde cuando todo está bien: una ✗ roja ahora SÍ significa que algo se dañó.
