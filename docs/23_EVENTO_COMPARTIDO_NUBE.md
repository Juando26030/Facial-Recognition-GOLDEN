# Evento compartido entre varios servidores locales, con la nube como puente (20-nov-2026)

**Estado:** desarrollado en la rama `feat/evento-compartido-nube` (migración `0160_shared_local_events`). **No desplegado.** Pedido de Juan David el 20-nov-2026.

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
- `events.local_shared`: el evento acepta varios servidores. Lo enciende o apaga cualquiera que pueda llevar eventos a local (Editar evento › Servidor local). Apagarlo solo con uno o ningún servidor.
- `event_local_nodes`: qué servidores tienen el evento. El primero sigue en `events.local_node_name` (el «principal»), así todo lo que ya leía esa columna sigue igual.
- `event_lease.is_writer` reemplaza la comparación «¿es el servidor que lo tiene?» en todos los puntos donde un servidor escribe o baja datos (paquete, checklist, subidas, liberar).
- **Pasar a internet** desde un servidor: sale solo ese servidor; el evento vuelve a la nube cuando sale el último. Si salió el principal, el siguiente pasa a serlo.
- `/api/node/ping` devuelve `shared_events`: un servidor que ya tenía el evento se entera en su ciclo normal (≤ 30 min, o «Sincronizar») de que ahora es compartido. **Lo recomendado es marcarlo antes de descargarlo.**
- `/api/node/events/{id}/changes?l=&a=&p=&c=`: registros, personas del evento, impresiones y cambios con id mayor al cursor, en páginas de 500. Solo para servidores del grupo.

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

Cada tipo tiene su marca de agua en el evento local (`sync_edit_id`, `sync_area_id`, `sync_delivery_id`, `sync_turn_id`, `sync_call_id`, `sync_turn_at`) y cuenta en «pendientes»: «Pasar a internet»
no libera mientras falte algo. Áreas, entregas y turnos salieron de la lista de «solo local» que bloqueaba la liberación. Quedan en esa lista (no suben todavía): cambios del inventario de
ALMACÉN del evento (en el servidor local es de solo consulta), sorteos de la ruleta, contactos de expositores, aceptaciones/firmas y autorizaciones de datos.

## 4. Conflictos y límites (primera versión)
- **Misma persona en las dos entradas durante un corte:** quedan los dos registros (como en el modo sin red de los quioscos); la nube los conserva y se ven en el historial. La regla de negocio de cada evento decide qué hacer.
- **Misma persona dada de alta en las dos entradas:** gana la primera alta que llegó a la nube; la segunda queda como registro de una persona existente.
- **Turnos en eventos compartidos:** cada entrada debe usar **sus propias filas (letras)**; si dos servidores dan el mismo número de la misma fila a personas distintas, el segundo se omite
  (queda contado como conflicto). Los otros servidores reciben los turnos nuevos y los llamados; «atendido/saltado» sube a la nube pero no se reparte a los demás servidores.
- **No viaja todavía:** rostros/biometría (el servidor local no hace reconocimiento facial), ruleta, contactos de expositores, aceptaciones/firmas y autorizaciones de datos.
- **Estado del evento:** cada servidor pone su copia «En proceso» como siempre; la sincronización rápida solo corre en ese estado.

## 5. Costo
Por servidor: 1 subida (solo si hay algo nuevo) + 1 consulta de cambios cada 15 s ≈ 240 peticiones/hora, unos pocos KB cada una. En Cloud Run es del orden de centavos de dólar por evento.
Lo que más pesa es que la base (Neon) no se duerme mientras el evento compartido está «En proceso» con internet (≈ 0,25 CU por hora). Fuera de «En proceso» no se consulta la nube más de lo normal.
`NODE_SHARED_SECONDS` sube el intervalo si se quiere gastar menos (con más demora en verse).

## 6. Pruebas
`tests/test_evento_compartido.py`: un solo escritor si no es compartido; dos servidores en un evento compartido se ven por `/changes`; salen uno a uno; no se deja de compartir con dos dentro;
el ping avisa; aplicar lo bajado es idempotente, salta el eco propio y no pisa datos; el ciclo corto sube con prefijo propio, baja y nunca devuelve lo bajado.

## 7. Pendiente antes de producción
1. Ensayo real con dos servidores locales y dos redes distintas (por ejemplo una con Starlink), registrando a la vez en las dos entradas, cortando internet en una y volviendo.
2. Medir la demora real entre entradas y el consumo de datos (para el plan de Starlink).
3. Decidir si en eventos compartidos se avisa en el quiosco «registrado en la otra entrada a las …» (hoy se ve como un registro más).
