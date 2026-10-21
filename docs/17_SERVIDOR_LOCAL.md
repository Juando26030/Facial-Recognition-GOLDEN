# Servidor local para eventos sin internet, con sincronización a la nube (diseño)

Necesidad (Juan David, 2026-10-05): hay eventos en lugares sin internet estable o sin señal (pueblos alejados). Antes se montaba el software en un equipo que hacía de servidor y se le conectaba un router;
los demás equipos se conectaban a él. Ahora: **sin instancia de software aparte por servidor** (nada de «otro sistema con sus eventos y usuarios»): el servidor local trabaja con el MISMO sistema y apenas
tenga internet sincroniza con la nube; si solo el servidor tiene conexión, hace una copia automática del evento a la versión de la nube. Restricciones: **cero presupuesto de hardware nuevo**, laptops
Windows de la empresa, 5-6 equipos (celulares, tabletas, laptops) por router; más carga = más routers o hasta 2 laptops servidoras.

## 1. Opciones evaluadas
| Opción | Cómo sería | A favor | En contra |
|---|---|---|---|
| **A. Contenedores (Docker Desktop) en la laptop** | `docker compose` con la MISMA imagen de la nube (`golden-app`) + PostgreSQL | Mismo código y mismas migraciones que la nube (sin una segunda versión que mantener); ya existen la imagen y `deploy/docker-compose.yml`; días para un piloto | Docker Desktop en Windows necesita virtualización activada y ~2-4 GB de RAM; arranque lento; hay que confirmar la licencia y que las laptops lo soporten |
| **B. Nativo en Windows** (Python + PostgreSQL + dlib instalados por un script) | Un instalador deja el servicio andando | Más liviano; sin virtualización | Hay que mantener un instalador y las versiones de dlib/PostgreSQL en Windows; más trabajo y más cosas que pueden fallar en campo |
| **C. Solo web instalable (PWA) sin servidor** | Cada equipo guarda todo en su navegador | Nada que instalar | NO sirve para varios equipos en la misma red (cada uno tendría datos distintos); es lo que ya hace el modo contingencia como respaldo de un equipo |
| D. SQLite en vez de PostgreSQL | App más liviana | — | El código usa funciones propias de PostgreSQL (`FOR UPDATE`, `xmin`, funciones PL/pgSQL, JSONB): sería otra versión de la aplicación. Descartada |

**Recomendación:** empezar con **A** como piloto (rápido y fiel a la nube), medir en una laptop real de las que usarán, y dejar **B** como plan alternativo si Docker no es confiable en esas laptops. El modo
contingencia actual (lista local en cada navegador) queda como último respaldo si el servidor falla.

## 2. HTTPS en la red local (el punto técnico más delicado)
La cámara (`getUserMedia`), el service worker del quiosco y la impresión USB (WebUSB, B1) **solo funcionan en un contexto seguro**: `https://` o `localhost`. Una dirección como `http://192.168.1.10` NO lo es.
Opciones para los celulares/tabletas:
1. **Autoridad certificadora local**: el servidor genera su propia CA y un certificado para su IP/nombre; cada equipo de Golden instala la CA UNA vez (Android: Ajustes → Seguridad → instalar certificado de
   CA; Chrome la acepta). Limpio y administrable; requiere un paso por equipo.
2. **Bandera de Chrome** «Insecure origins treated as secure» (`chrome://flags`) con la dirección del servidor: sin certificados, pero se configura a mano en cada dispositivo y es frágil.
3. Dominio propio apuntando a la IP privada con un certificado público: necesita DNS local en la red sin internet; descartado por complejidad.
Se prueba la opción 1 en el piloto y se deja la 2 como salida de emergencia.

## 3. Modelo de sincronización
- **Un solo escritor por evento («arrendamiento»).** Antes de salir, el servidor local «toma» el evento: la nube lo marca *en servidor local* (con el nodo y la hora) y deja de aceptar registros de ese evento
  (los usuarios de la nube lo ven en solo lectura con un aviso). Un administrador puede recuperarlo (se rompe el arrendamiento) mostrando la última sincronización. Esto evita el problema de fusionar datos
  cambiados en dos sitios.
- **Bajada (paquete del evento):** el evento y su configuración (parámetros, campos, plantilla de escarapela), las personas y asistentes del evento, y los usuarios con acceso a ese evento (con su clave ya
  protegida, para entrar sin internet). Los rostros: las codificaciones faciales viajan cifradas y el servidor necesita la `FACE_ENCRYPTION_KEY` para usarlas; se entrega al preparar el servidor, nunca se guarda
  en el repositorio, y la laptop va con el disco cifrado (BitLocker). La retención biométrica (7 días tras finalizar) aplica igual.
- **Subida (bandeja de salida):** todo lo que el servidor escribe de ese evento (ingresos, personas y asistentes nuevos o editados, movimientos de áreas, impresiones, fotos) se registra en una bandeja de salida
  y se envía en lotes cuando hay internet, con **identificador único por registro** (el mismo mecanismo idempotente del modo contingencia: reenviar nunca duplica) y confirmación antes de borrar de la bandeja.
  Las fotos suben aparte. La nube aplica los cambios y marca hasta dónde llegó.
- **Copia al vuelo:** si solo el servidor tiene internet, el mismo proceso sube en segundo plano cada pocos segundos; los demás equipos siguen hablando con el servidor por la red local.
- **Versión:** el servidor informa su versión (commit y esquema); la nube rechaza una subida incompatible y dice qué actualizar. Nunca se sincroniza entre versiones que no coinciden.
- **Seguridad:** el servidor se identifica con un token propio por nodo (se puede revocar), todo por HTTPS hacia la nube; el panel de estado muestra último paquete bajado, última subida y cuántos registros esperan.

## 4. Fallas y límites
- **Sin internet:** el servidor puede trabajar todo el evento (días); el límite real es el disco y la energía. La bandeja de salida crece solo con registros (pequeños) y fotos.
- **Se cae la laptop servidora:** se pierde lo que no se haya sincronizado. Mitigación: copia periódica de la base local a un disco USB o a una segunda laptop y sincronizar apenas haya cualquier internet (un celular
  compartiendo datos basta para subir lotes pequeños). Hasta que se pruebe, el modo contingencia (lista local en los navegadores) cubre un corte del servidor.
- **Más de 5-6 equipos:** otro router en el mismo servidor, o una segunda laptop servidora con SU propio evento o su propia mitad de equipos (no se reparten los mismos registros entre dos servidores en la primera versión).
- **Lo que NO hace en la primera versión:** formularios públicos con pago (siguen en la nube), ni dos servidores escribiendo el mismo evento.

## 5. Fases
- **E0 · Piloto (días):** laptop con la imagen actual en modo servidor, router y 3-4 equipos; elegir el HTTPS (sección 2); medir arranque, memoria y reconocimiento facial en una laptop real.
- **E1 · Paquete y bandeja de salida:** bajar un evento a la laptop y subir lo registrado, primero con un comando manual; arrendamiento en la nube; panel de estado.
- **E2 · Sincronización automática:** envío en segundo plano, reintentos, copia al vuelo, versión; pruebas de cortes de red y de energía.
- **E3 · Ensayo general:** un evento de ~8.000 personas simulado sin internet, caída de la laptop a mitad, recuperación y comparación con la nube (cero sobrantes, cero faltantes).

## 6. Preguntas abiertas
1. Modelo y memoria (RAM) de las laptops que harían de servidor, Windows 10/11 y si tienen la virtualización activada.
2. ¿Hace falta el reconocimiento facial sin internet, o basta cédula/QR/búsqueda en esos eventos? (dlib en una laptop es posible pero más lento que la nube).
3. Duración típica de un evento sin internet y cuántos registros nuevos (personas que no están en la lista) se esperan.
4. ¿Quién arma y verifica el servidor antes de salir? (define cuánta automatización necesita el paso de preparación).
