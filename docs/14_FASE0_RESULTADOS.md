# Fase 0 — resultados, decisiones y lo que falta (rama `perf/fase0-carga`, 2026-09-26)

Resumen de lo hecho para que la app aguante picos **antes** de migrar la infraestructura (`13_ARQUITECTURA_ESCALABILIDAD.md`). Todo se probó **solo en local** (nunca contra
producción), con una base sintética de 8.000 personas. Nada de esto está desplegado ni fusionado a `main`.

## 1. Hallazgos del §2 del doc 13 sobre el código actual (`main` = `1e53943`)

| # | Hallazgo del doc | ¿Persistía? | Comentario |
|---|---|---|---|
| 1 | Un proceso; endpoints `async def` con SQLAlchemy síncrono bloquean el hilo | **Sí, y era peor** | La prueba de carga lo reproduce y además **cuelga el servidor por completo** (ver §2): 15 peticiones esperando su cuerpo retenían las 15 conexiones del pool y la 16.ª bloqueaba el bucle de eventos, así que ninguna podía terminar. No se recupera solo. |
| 2 | Cada escaneo facial trae y descifra a TODAS las personas del cliente y compara en un bucle Python | Sí | Con 8.000 personas: **10 s por escaneo** con solo 2 estaciones. |
| 3 | `num_jitters=10` y foto sin reducir | Sí | La carga masiva ya reducía a 1024 px; el escaneo no. |
| 4 | Sin «registro automático», cada persona se reconoce DOS veces | Sí | El navegador reenviaba la foto al confirmar. |
| 5 | Formularios: bloqueo `FOR UPDATE` del cupo y conteos en cada apertura | Sí | Y encontré **más** (ver abajo). |
| 6 | Directorio: lista completa en cada refresco | Sí | Y cada fila descifraba `face_encoding` sin usarlo. |
| 7 | App y base en la misma VM | Sí (infra) | Es de la Fase 1. |

**Hallazgos nuevos (no estaban en el doc):**

* **Pool agotado = servidor colgado** (arriba): pool por defecto de SQLAlchemy (5+10) y peticiones `async` que retienen su conexión mientras esperan el cuerpo. Es la causa más probable de una caída total.
* **Login (`bcrypt`) dentro del bucle de eventos**: cada inicio de sesión congelaba a todos ~0,3 s.
* **Contar cupos por variables releía y decodificaba el JSON de TODAS las inscripciones dentro del bloqueo del formulario**: con miles de inscripciones cada envío tardaba más que el anterior.
* **Cada visita a un formulario público escribía y borraba en la tabla de límites** (`rate_limit_events`) — una escritura de base por apertura.
* **Correo y carga a la base del evento dentro de la petición de envío**, y un `except: pass` que ocultaba fallos del envío de la escarapela.
* Faltaban índices de los caminos calientes (`access_logs(event_id, user_id)`, inscripciones por formulario/estado/sid, pagos por estado/fecha…).
* Reportes Excel dejaban un temporal en disco por cada descarga (nunca se borraba) y no tenían tope de concurrencia.
* Un dominio de producción escrito en el código (escarapela digital) y `date.today()` (hora local del servidor) en la retención.

## 2. Antes y después (prueba de carga local)

**Método.** Locust contra un servidor local y la base sintética `golden_load` (8.000 personas, un evento en curso con auto-registro, un formulario abierto), todo en **la misma máquina de desarrollo** (Windows: el servidor, dlib y los 200-300 usuarios virtuales compiten por la misma CPU, así que los números absolutos son conservadores y **no son la capacidad de la VM de producción**). 45 s por escenario, cada usuario virtual con su propia IP. «Antes» = `main` (`1e53943`) con 1 proceso; «Después» = esta rama con 3 procesos (la configuración de producción). Las tablas completas están en `C:\JDRJ\Golden\perf_results` (fuera del repo). Escala 100 % = 300 usuarios de formulario, 200 estaciones de cédula, 20 de facial.

| Escenario | Métrica | Antes (main, 1 proceso) | Después (rama, 3 procesos) |
|---|---|---|---|
| (a) formulario: abrir + enviar, 300 usuarios | Envíos que terminan | **0** (servidor colgado; 100 % de fallos) | **4.768**, 0 fallos (108 envíos/s) |
| | p50 / p95 del envío | — (nunca respondió) | 160 ms / 380 ms |
| | Apertura de la página (p50) | 1.000 ms, 48 % de fallos | 100 ms (p95 260 ms) |
| (b) cédula, 200 estaciones (meta ~57/s) | Acreditaciones en 45 s | 37 (**0,8/s**) | 2.477 (**56/s**) |
| | p50 / p95 | 5.600 ms / 5.800 ms | 7 ms / 120 ms |
| (c) facial, 20 estaciones (~6/s pedidos) | Escaneos atendidos | 0 en 45 s (p50 de 11 s aun con 2 estaciones) | ~0,7/s atendidos; el resto recibe 503 inmediato con «reintenta» (ver §5) |
| (d) mezcla 60/30/10, 200 usuarios | Páginas / envíos / cédulas por segundo | 0,1 / 0 / 0 (colgado) | 50 / 50 / 25 por segundo, **0 fallos** en formularios y cédula |
| | p50 (página / envío / cédula) | 3 s a 33 s | 6 ms / 13 ms / 11 ms (p95 ≤ 390 ms) |
| (e) directorio de 8.000, 20 pantallas | p50 de cada carga | 36.000 ms | 1.100 ms (y **304 sin cuerpo** si nada cambió) |
| Reconocimiento (1 escaneo, 8.000 personas) | Tiempo | ~10 s (todo el trabajo en el hilo web) | ~2,4 s de CPU **en un proceso aparte**: mientras corren 3 escaneos, una cédula responde en ~25 ms |

Corridas al 10 % de usuarios (carga ligera, 1 proceso): antes, el envío del formulario ni siquiera terminaba (30 usuarios ya lo colgaban); después, p50 8 ms y 0 fallos.

## 3. Qué cambió (resumen; el detalle técnico está en `CLAUDE.md`, sección «Fase 0»)

Tareas del brief: hilos y pool (§8.1), candidatos del evento + matriz en memoria (§8.2), foto reducida (§8.3), token anti-doble reconocimiento (§8.4), jitters medidos y no cambiados (§8.5), cédula con `client_id` (§8.6), formularios (§8.7-8.9), conciliación de pagos (§8.10), directorio (§8.11), reportes con tope (§8.12), base de datos (§8.14), sin dlib al importar (§8.15). Además: ingreso idempotente y sincronización por lotes, `APP_MODE` con tres entry points (preparado, inactivo), Gunicorn, y lo de compatibilidad con Cloud Run + Neon (almacenamiento, cola, salud, logs, apagado ordenado).

## 4. Decisiones que tomé ante ambigüedades (y por qué)

1. **Candidatos = personas del evento** (no del cliente), como pide el doc. Efecto: alguien de otro evento del mismo cliente ya no se reconoce «de rebote» en éste; debe estar en la base del evento. Es lo más seguro con eventos simultáneos.
2. **El cálculo facial va en procesos hijo, no en hilos.** Medí que dlib retiene el GIL: en un hilo, un escaneo congelaba cédulas y formularios del mismo proceso. Los hijos corren con prioridad baja y mueren si muere el proceso web.
3. **Cola facial con rechazo rápido** (`FACE_QUEUE_TIMEOUT=1 s`, `FACE_CONCURRENCY=4`): esperar turno ocupaba hilos que necesitan cédulas y formularios (con espera de 20 s, cédulas y formularios llegaron a tardar 20 s). Con la cola llena se responde 503 + `Retry-After: 3` y el kiosco reintenta.
4. **Límite por IP de los formularios en memoria**, no en Postgres (era una escritura por visita). Con 3 procesos el tope efectivo es ×3; para wifis compartidas está `PUBLIC_LIMIT_FACTOR` (ver runbook).
5. **Estado público del formulario en caché de 5 s** (y cascarón con `s-maxage=60`): lo que importa (cupo, duplicados, precio) se vuelve a comprobar al enviar. No hay purga de Cloudflare (exigiría credenciales o recursos de nube).
6. **Envío idempotente por `sid`**: mismo `sid` + misma persona = reintento (200 con `replayed`); otra visita con la misma cédula sigue siendo duplicado (409).
7. **Directorio:** ETag con `xmin` de Postgres (barato y exacto). La interfaz sigue pidiendo la lista completa; paginación e incremental existen en la API, pero cablearlos a la UI cambia la búsqueda: es de la Fase 1.
8. **`num_jitters` NO se tocó** (10). Ver §6.
9. **Gunicorn:** 3 procesos (`WEB_CONCURRENCY`). No pude ejecutarlo (Windows / Python 3.14); lo verifiqué con `uvicorn --workers 3` (mismo código de la app). La vuelta atrás está documentada en el unit.
10. **Escarapela digital sin dominio por defecto:** sin `PUBLIC_BASE_URL` ni petición, no se envía el correo (antes caía a un dominio de producción escrito en el código).
11. **Reportes:** 1 a la vez por proceso; los demás reciben 503 «reintenta en un minuto» (contención, no cola; el Cloud Run Job es de la Fase 2).

## 5. Límites conocidos (no prometer de más)

* **Escaneo facial: ~0,4-0,7 escaneos/s por proceso hijo** a 10 jitters en esta máquina. La meta de ~57/s (cédula **o** facial) se cumple para **cédula** (56/s medidos); para **facial** no se alcanza con 10 jitters y una CPU: hace falta bajar jitters (§6) y/o más cómputo (Fase 2, servicio de biometría con escalado). El doc 13 dice que el objetivo facial se fija tras medir: **este es el costo medido**.
* 5.000 envíos simultáneos reales (10.000 aperturas) no se pueden generar desde el mismo equipo que el servidor; lo medido es ~108 envíos/s sostenidos con 0 fallos con 300 usuarios virtuales. Demostrar 5.000/10.000 es la prueba de la Fase 4 contra staging.
* El envío con **pago** depende de Wompi; solo se probó con pruebas automáticas.
* Las cargas masivas con fotos siguen en un hilo del proceso web (`bulk_jobs`): el cálculo ya va a los procesos hijo, pero la subida directa a Cloud Storage es de la Fase 2.
* Con 1 proceso y 200 usuarios mezclados se ven pausas de ~10 s (pool de base agotado): por eso producción usa 3 procesos.

## 6. `num_jitters`: medición y recomendación

`scripts/bench_jitters.py` mide tiempo y desviación frente a 25 jitters y, si las fotos están agrupadas por persona, aciertos y falsos positivos con el umbral 0,55. **`C:\JDRJ\Golden\fotos_prueba` no existe en esta máquina**, así que solo pude medir **tiempo** con una foto de dominio público (una sola imagen: la desviación no equivale a precisión):

| jitters | ms por encoding (640 px) | desviación vs 25 (1 foto) |
|---:|---:|---:|
| 1 | 550 | 0,122 |
| 2 | 1.067 | 0,111 |
| 5 | 2.330 | 0,073 |
| 10 (actual) | 4.621 | 0,031 |
| 25 (registro) | 11.652 | 0 |

El costo es casi lineal (~0,46 s por jitter): **1-2 jitters serían 5-8 veces más rápidos** que 10, y la desviación (0,12) queda lejos del umbral de coincidencia (0,55). **Recomendación:** medir la precisión real corriendo `python scripts/bench_jitters.py` con las fotos de prueba en una carpeta por persona; si con 2 jitters no bajan los aciertos ni suben los falsos positivos, poner `RECOGNITION_JITTERS=2` en el `.env` (no requiere código). Hasta medirlo, sigue en 10.

### 6.1 Medición con fotos reales (2026-09-27)

`C:\JDRJ\Golden\fotos_prueba`: 4 personas con consentimiento, una foto de registro y una de kiosco por persona (bajadas de WhatsApp,
.jpg y .jpeg). Corrido dentro de la imagen Docker (`golden-app:local`, Python 3.14, CPU del PC de desarrollo), con la carpeta montada en
solo lectura. Simulación del escaneo real (`scripts/bench_jitters.py`, modo registro/kiosco): los registros se enrolan como en producción
(25 jitters, resolución completa) y cada foto de kiosco se identifica como `app/faces.identify` (rostro más grande, 640 px, la persona más
cercana si la distancia < 0,55). 20 escaneos por valor (4 fotos × 5 repeticiones, para estabilizar el tiempo).

| jitters | aciertos | falsos positivos | no detectados (sin rostro / sin coincidencia) | ms promedio por escaneo | dist. media al correcto | dist. mínima a otra persona |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20/20 | 0 | 0 / 0 | 133 | 0,289 | 0,712 |
| 2 | 20/20 | 0 | 0 / 0 | 221 | 0,282 | 0,696 |
| 5 | 20/20 | 0 | 0 / 0 | 475 | 0,273 | 0,714 |
| 10 (actual) | 20/20 | 0 | 0 / 0 | 901 | 0,272 | 0,704 |

Todas las parejas de fotos (registro y kiosco mezclados): aciertos misma persona 100 % y 0 falsos positivos con 1, 2, 5, 10 y 25 jitters;
desviación máxima frente a 25 jitters: 0,12 (1), 0,10 (2), 0,06 (5 y 10).

**Recomendación: `RECOGNITION_JITTERS=2` en producción.** Con 2 jitters el escaneo cuesta ~4 veces menos que con 10 (221 ms frente a
901 ms) y la precisión medida no cambia: la distancia a la persona correcta sube solo 0,01 (0,28 frente a 0,27) y el margen hasta el
umbral sigue siendo enorme (0,28 contra 0,55; la persona equivocada más cercana quedó a 0,70). Se prefiere 2 y no 1 porque cuesta solo
~90 ms más y reduce a la mitad la diferencia frente al encoding de referencia (0,10 frente a 0,12 en el peor caso), un colchón barato
para fotos de kiosco peores que estas (contraluz, ángulo). **Límite de la muestra:** 4 personas y 24 parejas de personas distintas no
bastan para estimar la tasa de falsos positivos de un evento de miles (el riesgo real son los parecidos). Antes de un evento grande,
repetir con ≥30 personas; si aparece algún falso positivo o un "sin coincidencia" con 2 que no salga con 10, volver a 10.

### 6.2 Segunda medición: 39 personas (2026-09-28)

`C:\JDRJ\Golden\fotos_prueba`: 40 carpetas anónimas con consentimiento; **una está vacía, así que la muestra real es de 39 personas**
(una foto de registro y una de kiosco cada una; formatos .jpg, .jpeg, .png, .webp y .avif — el script ahora lee los cinco: en una primera
corrida solo leía .jpg/.jpeg/.png, dejó fuera 30 fotos y sus números se descartaron). Misma forma de medir que en 6.1: dentro de la imagen
Docker, carpeta montada en solo lectura, registros enrolados como en producción (25 jitters, resolución completa) y cada foto de kiosco
identificada como `app/faces.identify` (rostro más grande, 640 px). 195 escaneos por valor (39 fotos × 5 repeticiones). Conjunto
cerrado: todas las personas escaneadas están registradas.

| jitters | umbral | aciertos | falsos positivos | sin coincidencia | sin rostro | ms por escaneo |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0,55 | 190/195 | 0 | 0 | 5 | 119 |
| 1 | 0,50 | 165/195 | 0 | 25 | 5 | 119 |
| 2 (producción) | 0,55 | 189/195 | 0 | 1 | 5 | 202 |
| 2 (producción) | 0,50 | 173/195 | 0 | 17 | 5 | 202 |
| 5 | 0,55 | 190/195 | 0 | 0 | 5 | 453 |
| 5 | 0,50 | 182/195 | 0 | 8 | 5 | 453 |

«Sin rostro» = una misma foto de kiosco (×5 repeticiones) en la que no se detecta cara a 640 px, con cualquier umbral y jitters.

Distancias de cada foto de kiosco contra todos los registros:

| jitters | misma persona: media | p95 | máxima | otra persona: mínima | p1 | margen (mín. otra − máx. misma) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0,412 | 0,526 | 0,530 | 0,584 | 0,645 | +0,054 |
| 2 | 0,402 | 0,510 | 0,555 | 0,542 | 0,638 | **−0,013** |
| 5 | 0,393 | 0,496 | 0,527 | 0,542 | 0,640 | +0,015 |

**Lectura.** (1) Con 0,55 los aciertos son 97-98 % y no hubo ningún falso positivo; con 0,50 se pierden 8-25 aciertos de 195 (4-13 %
de personas que el sistema ya no reconoce y deben ir por cédula) **sin ganar nada medible en falsos positivos** (tampoco hubo con 0,55).
(2) Pero el margen es muy estrecho: la persona equivocada más parecida quedó a 0,54-0,58, casi en el umbral, y con 2 jitters las dos
distribuciones incluso se tocan (una foto de la misma persona a 0,555 y el impostor más cercano a 0,542). No hubo falso positivo solo
porque en ese escaneo la persona correcta estaba registrada y quedó más cerca. **El riesgo real es alguien que NO está en la base y se
parece a alguien que sí** (conjunto abierto): esa persona podría quedar por debajo de 0,55. Con miles de personas en un evento aparecen
más parecidos y la distancia mínima a otra persona baja. (3) 1, 2 y 5 jitters dan la misma precisión con 0,55; 2 cuesta 202 ms.

**Recomendación: mantener 0,55 y `RECOGNITION_JITTERS=2`.** 0,50 haría que 1 de cada 8-12 personas no sea reconocida (a 1-2 jitters)
sin una mejora demostrada. La protección contra falsos positivos no debe depender solo del umbral: (a) con «registro automático»
APAGADO el operador confirma (ver abajo: hoy NO ve la foto de registro, conviene agregarla); (b) con «registro automático» ENCENDIDO en
un evento grande, conviene una regla extra además del umbral: **exigir distancia < 0,55 Y que la segunda persona más cercana esté al
menos ~0,06 más lejos** (si dos personas quedan casi empatadas, se pide confirmación o cédula). Esa regla no está implementada: es una
propuesta para medir con esta misma prueba antes de activarla. **Límite de la muestra:** 39 personas en conjunto cerrado (1.482
comparaciones contra otras personas por repetición); sirve para comparar valores, no para estimar la tasa de falsos positivos de un
evento de miles. Antes de un evento con registro automático encendido y más de ~1.000 personas con rostro, repetir con más personas y
con fotos de personas NO registradas.

**¿El operador ve la foto de registro antes de confirmar?** No. Con «registro automático» apagado, `/api/recognize` responde
`MATCH_PENDING` y la pantalla del kiosco (`app.js` → `fillProfileCard`) muestra solo campos de texto editables (nombres, cargo, entidad…)
y el mensaje «Coincidencia encontrada — confirma para autorizar el acceso»: ni la foto registrada ni qué tan parecida es. El operador
confirma por el nombre, sin comparar caras. **Propuesta (no implementada):** en esa tarjeta, mostrar lado a lado la foto de registro
(`GET /api/users/{id}/photo?event_id=…`, ya existe: exige sesión y acceso al evento, sirve la foto descifrada con `Cache-Control:
private, no-store`) y la captura del momento (ya está en el navegador, no hay que subirla de nuevo), más un indicador de parecido en
palabras (p. ej. «muy parecido» < 0,40, «parecido» 0,40-0,50, «revisar con cuidado» 0,50-0,55) y, si la segunda persona más cercana
queda casi empatada, un aviso con su nombre. La foto solo se muestra en ese momento y no se guarda en el navegador. Costo: una petición
de ~50-100 KB por confirmación.

## 7. Estado por proceso (revisado antes de pasar a varios procesos)

Revisé todo el estado en memoria a nivel de módulo:

* **Sesión:** cookie firmada (sin estado en el servidor). **Límites de login, restablecer contraseña y certificados:** en Postgres. **Cargas masivas:** estado en Postgres (el hilo vive en el proceso que la creó; cualquiera puede consultar el avance). **Ruleta, cupos y pagos:** bloqueos de fila en Postgres.
* **Solo cachés con vencimiento o versión:** estado público de formularios (5 s), matriz facial (versión `events.faces_version`), tasas de cambio y estado de Wompi. **Límite por IP de formularios:** en memoria (decisión 4).
* No queda nada que dependa de un único proceso.

## 8. Qué probar en local antes de aprobar el merge

1. `alembic upgrade head` sobre una copia de la base real (migraciones **0047** y **0048**) y `python -m pytest -q` (313 pruebas).
2. Formulario público: abrirlo, enviarlo (con y sin pago de prueba), reintentar con la red cortada (DevTools → Offline) y comprobar que no se duplica; probar un cupo por variables.
3. Kiosco: escaneo facial de alguien de la base (con y sin registro automático: el segundo paso ya no reenvía la foto) y por cédula.
4. Directorio en vivo con un evento grande (debe verse igual).
5. `/sistema` como administrador, `/healthz` y `/readyz`.
6. **Con fotos reales:** `python scripts/bench_jitters.py` (recomendación de §6).
7. En la VM (después del merge, con un evento sin actividad): `pip install -r requirements.txt` (agrega gunicorn), reiniciar y comprobar `curl localhost:8000/readyz`; agregar `OPS_TOKEN` al `.env`.

## 9. Lo que queda para las Fases 1-4

* **Fase 1:** archivos a Cloud Storage (`GcsStorage` con la interfaz de `app/storage.py`), base a Neon (pooler, `DIRECT_DATABASE_URL`), paginación e incremental en la UI del directorio, respaldo propio, alertas.
* **Fase 2:** Dockerfile, tres servicios (`app/entrypoints/`), cargas y reportes como Cloud Run Jobs, correo por Cloud Tasks, despliegue sin llaves.
* **Fase 3:** modo contingencia del kiosco (la API idempotente ya está: `client_id` y `/access-logs/sync`).
* **Fase 4:** prueba de carga contra staging (10.000 aperturas / 5.000 envíos / 57 escaneos/s) y simulacros de falla.

