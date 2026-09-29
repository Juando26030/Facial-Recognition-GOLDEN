# Arquitectura resiliente para picos de carga, con presupuesto de US$40/mes (v3, 2026-09-26)

> Continúa `12_INFRAESTRUCTURA_HOSTING.md`. Requisito de Juan David: los
> formularios web deben aguantar **5.000 o más inscripciones al mismo
> tiempo** (apertura de cupos; "antes se caía"), y en paralelo pueden estar
> corriendo **5-6 eventos de ~8.000 personas** en distintos lugares, con
> **100-200 personas escaneándose a la vez** (cédula o rostro, una cada 3-4
> s por estación), toda la noche.
>
> **Restricciones añadidas el mismo día:** (1) presupuesto máximo de
> **US$40/mes** en nube; (2) **no se puede caer a mitad de una noche
> pesada**; (3) la base de datos también debe cobrar **por uso**; (4) debe
> encajar con cómo Google resuelve las fallas de máquina (migración en
> vivo, reinicio automático, grupos de instancias que se reconstruyen
> solos).
>
> Historial: v1 (Cloud SQL con alta disponibilidad + Cloud Run siempre
> encendido, ~US$300-370/mes) descartada por costo. v2 (Postgres en la VM
> e2-medium + Cloud Run) reemplazada por esta v3, que cambia la base de
> datos a una con cobro por uso y agrega las capas de resiliencia.

## Decisión en una línea

**Optimizar el código a fondo (costo cero), mover la aplicación a Cloud
Run y la base de datos a Neon (Postgres "serverless" que cobra por uso),
apagar la VM, y agregar un modo de contingencia en los kioscos para que la
entrada al evento siga funcionando aunque falle cualquier pieza de la
nube.** Costo estimado: **~US$22-35 en un mes típico**, con topes para no
pasar de ~US$40-44 en un mes muy cargado. Sin compromisos anuales.

## Sobre "imposible que se caiga" (dicho claro)

Ningún sistema en ninguna nube, a ningún precio, es literalmente
imposible de caer: Google promete 99,95% para Cloud Run, no 100%. Lo que
sí se puede diseñar, y es lo que hace este plan, es que **ninguna falla
individual detenga la entrada de la gente en el evento**: si falla una
máquina, otra toma su lugar sola; si falla la base de datos, se recupera
sola en segundos o minutos; y si falla todo lo de la nube (o el internet
del recinto), los kioscos siguen admitiendo gente por cédula o QR sin
conexión y sincronizan después. La prueba de que funciona no es el papel:
es el **simulacro** de la Fase 4, donde se tumban piezas a propósito en
medio de una prueba de carga.

## 1. Qué significa esa carga en números

Lo que tumba un sistema no es el total de la noche, es el **pico por
segundo**. 48.000 personas en 4 horas son solo ~3 personas/s en promedio.

| Escenario | Supuesto de diseño | Carga pico al servidor |
|---|---|---|
| Apertura de cupos | Diseñar para **10.000** personas que abren el formulario en ~1 minuto y lo envían en los 2 minutos siguientes | ~170 aperturas/s promedio, picos de ~500/s; ~80-250 envíos/s. Si los archivos estáticos no salen de la caché de Cloudflare, cada apertura son ~8-10 peticiones → miles de peticiones/s al servidor |
| Escaneo en 6 eventos simultáneos | 200 personas escaneándose en cualquier ventana de 3-4 s | ~57 escaneos/s sostenidos |
| – por **cédula** | Búsqueda indexada + registrar ingreso | Milisegundos por escaneo si está bien hecho |
| – **facial**, código actual | ~1-1,5 s de CPU por escaneo (estimado; ver §2) | ~70 vCPU ocupados si todo fuera facial — ninguna máquina única lo aguanta |
| – facial, optimizado | ~0,15-0,3 s de CPU por escaneo (estimado) | ~10-15 vCPU, repartidos entre instancias que Cloud Run agrega solo |

## 2. Por qué se cae hoy — revisado sobre `main` al 25-sep (commit `1e53943`)

1. **Un solo proceso atendiendo todo** (`deploy/facial-recognition.service`:
   `uvicorn ... --workers 1`, a propósito según el propio archivo) **y los
   endpoints son `async def` con trabajo bloqueante adentro**: consultas
   SQLAlchemy síncronas en todos lados, y dlib completo en
   `/api/recognize`. En FastAPI eso congela el único hilo que atiende:
   mientras se procesa un rostro (~1 s) o se espera una consulta, **nadie
   más es atendido** — ni formularios, ni cédulas, ni el dashboard. Lo
   mismo pasa con `POST /f/{evento}/{slug}/submit`. Con 5.000 personas
   enviando, todas pasan en fila india por ese hilo. **Esta es, casi con
   seguridad, la causa principal de las caídas.**
2. **Cada escaneo facial trae de la base a TODAS las personas del cliente**
   (`User.tenant_id == event.tenant_id`, no del evento), **descifra el
   encoding de cada una** (Fernet, `EncryptedText`), lo convierte de JSON y
   compara una por una en un bucle. Con 8.000 personas: 8.000 descifrados
   + 8.000 comparaciones por escaneo.
3. **`num_jitters=10` al reconocer** (la documentación de
   `face_recognition` dice que más jitters es proporcionalmente más lento;
   el default es 1) y **sin reducir la foto** en el escaneo en vivo (la
   carga masiva ya reduce a 1024 px; el escaneo no).
4. **Cuando el evento no tiene "registro automático", cada persona se
   reconoce DOS veces**: la primera petición devuelve `MATCH_PENDING`, y al
   confirmar, el navegador reenvía la misma foto y el servidor repite todo
   el cálculo facial. Dobla el costo facial.
5. **Formularios:** el cupo ya está bien protegido contra sobreventa
   (bloqueo de la fila del formulario con `FOR UPDATE`) y ya existe la
   reserva de 30 minutos para inscripciones en pago (`PENDING_HOLD`). Pero
   ese bloqueo hace que todos los envíos de un formulario pasen uno por
   uno: hay que mantenerlo lo más corto posible (solo verificar cupo,
   insertar y confirmar; nada más dentro). Y cada apertura de la página
   calcula los cupos restantes con consultas de conteo; con 10.000
   aperturas conviene un contador o una caché de pocos segundos.
6. **Directorio en vivo:** ya no tiene el problema de "una consulta por
   persona" (fue corregido), pero sigue devolviendo la lista completa en
   cada refresco. Con varios kioscos y eventos, conviene paginar y enviar
   solo lo que cambió.
7. **App y base de datos en la misma VM**: confirmado el 26-sep,
   `golden-biometrics-prod` es **e2-custom-2-4096** (2 vCPU, 4 GB) en
   **us-central1-a**, ~US$42/mes solo la máquina según la propia
   recomendación de Google (que sugiere bajar a e2-medium para ahorrar
   ~US$17; **no aplicarla**: se basa en el promedio de uso, no en los picos
   de evento, y la VM se apaga en la Fase 2 de todas formas). **Corrección con la
   facturación real (27-sep):** la cuenta de facturación ("Pago de
   Firebase", en pesos) muestra COP 77.346 del 1 al 26 de septiembre (la VM
   se creó el 9) y ~COP 4.600 por día, o sea **~COP 138.000 por mes
   completo (~US$33-35)** todo incluido. Está dentro del presupuesto, pero
   es casi todo costo fijo con la CPU al 0,7% promedio: el cobro por uso
   sigue siendo más barato y además aguanta los picos.

Los puntos 1-6 son de código: ninguna nube los arregla sola.

## 3. Por qué US$40 alcanzan

La carga de Golden es de picos: casi todo el mes el sistema está
tranquilo, y el esfuerzo se concentra en unas pocas noches y aperturas de
cupos. En vez de pagar una máquina encendida 24/7 para esas horas:

- **Cada petición cuesta muy poco** gracias a la optimización (§8).
- **La app (Cloud Run) y la base de datos (Neon) se encienden y crecen
  solas en los picos, y se apagan o encogen después.** Una noche pesada de
  6 eventos cuesta del orden de US$4-6 entre ambas; el resto del mes, casi
  nada.
- **Cloudflare (gratis) absorbe lo que puede** antes de que llegue a la
  nube: estáticos y la página del formulario público salen de su caché.
- **Topes** para que el "taxímetro" tenga techo (§6).

## 4. Arquitectura

```
                    Cloudflare (plan gratis)
      caché de estáticos y de la página del formulario, Turnstile
      anti-bots en formularios, protección DDoS básica
             │                                   │
  inscripciones.<dominio>                   app.<dominio>
             │                                   │
 Cloud Run "publico"          Cloud Run "web"                Cloud Run "biometria"
 formularios públicos         dashboard, kioscos, cédula     solo reconocimiento facial
 sin dlib → arranque rápido   sin dlib → arranque rápido     carga dlib
 escala 0 → tope              mín. 2 durante eventos         mín. 1 durante eventos con rostro
             └──────────────┬────────────┴───────────────────────────┘
             Google Cloud, región us-east4 (norte de Virginia), multi-zona
                            │ conexión cifrada (TLS) al pooler de Neon
            Neon Postgres, AWS us-east-1 (norte de Virginia) — cobro por uso
            autoescala 0,25 → 4 CU, datos replicados en varias zonas,
            restauración a cualquier minuto de los últimos 7 días
                            │
   Cloud Storage (us-east4): fotos, adjuntos, archivos de formularios,
   y un backup diario PROPIO de la base (independiente de Neon)
   Cloud Tasks: correos, escarapelas, alimentar BD
   Cloud Run Jobs: carga masiva de fotos, reportes pesados, backup diario

   En cada kiosco: modo contingencia (roster del evento guardado en el
   dispositivo, registra ingresos sin conexión y sincroniza al volver)
```

Por qué cada pieza:

- **Tres servicios desde la misma imagen Docker.** "web" y "publico" no
  cargan dlib, así que arrancan rápido y el escalado a cero casi no se
  nota. Una avalancha de inscripciones no toca los kioscos, y un pico de
  rostros no frena los escaneos por cédula.
- **Neon en vez de Postgres en una VM:** cobra por tiempo de cómputo usado
  (US$0,106 por "CU-hora", 1 CU ≈ 4 GB de RAM) y por GB guardado
  (US$0,35/GB-mes), se apaga sola tras 5 minutos sin uso, crece sola hasta
  el tope que se le fije, trae pooler de conexiones (hasta 10.000
  conexiones de cliente, modo transacción) y restauración a un minuto
  dado de los últimos 7 días en el plan Launch. No hay VM que mantener,
  parchear ni reconstruir.
- **Misma zona metropolitana:** Google `us-east4` y AWS `us-east-1` están
  ambas en el norte de Virginia, así que la latencia entre la app y la base
  debería ser de pocos milisegundos (**medir en la Fase 1 antes de
  migrar**). Desde Colombia, el norte de Virginia suele responder más
  rápido que São Paulo, y sirve bien para eventos en Norteamérica y
  Europa.
- **Comparación facial:** los encodings están cifrados en la base con la
  llave de la app (buena decisión de privacidad, se mantiene: Neon nunca
  los ve en claro). Por eso la comparación se hace en la app: cada
  instancia de "biometria" carga una sola vez los encodings **del evento**
  (8.000 × 128 números ≈ 8 MB), los descifra una vez y compara todo en una
  sola operación de numpy. Un número de versión por evento avisa cuando
  alguien nuevo se registró, para recargar solo lo necesario.
- **Backup propio aparte del de Neon:** si algún día Neon tuviera un
  problema grave o hubiera que salir de ahí, existe una copia diaria en
  Cloud Storage de Google para restaurar en otro Postgres.

## 5. Cómo responde a cada falla (integra lo que vimos sobre Google)

Antes, con la VM, la protección era: migración en vivo si falla el
hardware, reinicio automático si la VM se cae, y la propuesta de un grupo
de instancias administrado (MIG) para reconstruirla si muere. **Con esta
arquitectura ya no hay VM que cuidar: Cloud Run hace por dentro lo que
hacían la migración en vivo y el MIG, de forma automática y en varias
zonas.**

| Qué falla | Con la VM de hoy | Con esta arquitectura |
|---|---|---|
| Hardware físico de Google | Migración en vivo (sin caída) o reinicio (1-2 min caído) | Google reemplaza la instancia sola. En eventos hay 2 instancias mínimas de "web": la otra sigue atendiendo, sin caída |
| La máquina/instancia muere del todo | Recrearla a mano (o con un MIG, 2-5 min) | Cloud Run crea otra sola (esto ES lo que hacía el MIG, ya incluido), en otra zona si hace falta |
| Una zona entera de Google | Todo caído | Cloud Run es regional: sigue en las otras zonas (99,95% mensual comprometido) |
| La base de datos: su servidor | Postgres caído hasta el reinicio | Neon levanta otro cómputo solo: segundos si falla la VM, 1-2 min si falla el nodo, 1-10 min si falla la zona. **Los datos no se pierden** (replicados en varias zonas). Mientras tanto: kioscos en contingencia y formularios reintentando |
| Toda la región, o un proveedor completo | Todo caído | Kioscos en contingencia siguen admitiendo por cédula/QR; formularios esperan. Backup propio en Cloud Storage para restaurar en otro lado |
| Internet del recinto | Kioscos sin servicio | Modo contingencia |
| Un despliegue con errores | Caída | No se despliega mientras haya un evento en curso o una apertura cercana; si algo sale mal, se vuelve a la versión anterior en segundos (Cloud Run guarda cada versión) |
| Más gente de la esperada | Caída | Crece hasta el tope; topes medidos con margen de 2x en la prueba de carga |
| Bots o ataque | Caída | Cloudflare + Turnstile + topes |
| Un kiosco físico | Ese punto de entrada | Los demás siguen; tener un dispositivo de repuesto por evento |

**Lo que no cubre este presupuesto:** Neon en plan Launch no trae SLA
contractual (solo el plan Scale, ~2x el precio por CU-hora). El riesgo se
compensa con el modo contingencia y el backup propio. Si más adelante el
negocio lo justifica, subir a Scale es un cambio de plan, no de
arquitectura.

## 6. Costo estimado (precios de lista)

| Componente | Supuesto | ~US$/mes |
|---|---|---|
| Neon Postgres, plan Launch | ~60 CU-h de uso diurno del staff + ~37 CU-h en ventanas de evento (mín. 0,5 CU) + ~20 CU-h de picos (noches pesadas y aperturas) ≈ 117 CU-h; 2-5 GB | ~13-19 |
| Cloud Run, uso real | 2 noches pesadas + 10 normales + aperturas, menos la capa gratis mensual | ~5-12 |
| Cloud Run, instancias mínimas en ventanas de evento | 2 × "web" (1 vCPU) + 1 × "biometria" (2 vCPU), ~74 h/mes | ~3-7 |
| Cloud Storage | Fotos, adjuntos, backups | ~1-3 |
| Tráfico saliente | Reducido por la caché de Cloudflare | ~1-3 |
| Cloud Tasks, Cloud Scheduler (3 tareas gratis), Artifact Registry, Monitoring | | ~0-1 |
| Cloudflare plan gratis, Turnstile | | 0 |
| Correo (§10) | Buzón actual en cola, o Amazon SES | 0 o ~US$0,10 por 1.000 |
| **Total** | | **~US$22-35 típico; ~US$40-44 en un mes muy cargado** |

Se eliminan la VM (US$24,46), su IP (~US$3,65) y su disco (~US$2), y ya
no hace falta un compromiso de 1 año. Durante la migración habrá un mes
con la VM y lo nuevo a la vez.

**Topes (obligatorios):**
- Neon: autoescalado con máximo de 4 CU (se puede subir a mano para una
  noche excepcional).
- Cloud Run: máximo de instancias por servicio (inicial sugerido: 10; se
  ajusta con la prueba de carga).
- Alertas de presupuesto de Google Cloud al 50%, 90% y 100% de US$40
  (avisan, no apagan) y revisión mensual del consumo de Neon.
- Turnstile en formularios públicos para que los bots no llenen cupos ni
  hagan crecer la factura.

## 7. Operación en noches de evento

- **Precalentamiento automático.** La app ya sabe cuándo hay eventos en
  curso y cuándo abre un formulario (estados programados). Una tarea
  programada (Cloud Scheduler) revisa cada pocos minutos y: sube a 2 las
  instancias mínimas de "web" (y a 1 las de "biometria" si el evento usa
  rostro) durante los eventos; sube "publico" unos minutos antes de una
  apertura; en Neon desactiva el apagado automático y fija un mínimo de
  0,5 CU durante esas ventanas. Después lo devuelve todo a cero.
- **Congelamiento de despliegues:** el flujo de despliegue consulta a la
  app y se niega a publicar si hay un evento en curso o una apertura en
  las próximas horas, salvo que alguien lo fuerce a propósito. Nunca se
  corren migraciones de base de datos en esas ventanas.
- **Vuelta atrás en segundos:** si una versión nueva falla, se redirige el
  tráfico a la anterior (Cloud Run conserva las versiones).
- **Monitoreo:** chequeos de disponibilidad de ambos subdominios cada
  minuto, alertas de errores y latencia al correo/celular.
- **Runbook de noche pesada:** qué revisar el día antes, quién mira el
  tablero, cómo activar el modo contingencia a propósito, cómo volver
  atrás.

## 8. Optimización de código (costo cero, lo que más rinde)

**Escaneo y biometría**
1. Quitar el cuello de botella del hilo único: los endpoints que usan
   SQLAlchemy síncrono pasan a `def` (FastAPI los reparte en un pool de
   hilos) y el cálculo facial va en un pool aparte. En la VM actual,
   además, varios workers de Uvicorn/Gunicorn (el estado de límites y
   cargas ya vive en Postgres; verificar que no quede nada que dependa de
   un único proceso).
2. Candidatos del **evento**, no del cliente; encodings del evento en
   memoria descifrados una vez, comparación en una sola operación numpy,
   recarga por número de versión.
3. **Reducir la foto en el navegador del kiosco** (~640 px, JPEG) antes de
   enviarla; detectar sin sobremuestreo y quedarse con el rostro más
   grande.
4. **No reconocer dos veces:** el primer reconocimiento devuelve un token
   de corta duración; la confirmación usa ese token en vez de reenviar la
   foto.
5. `num_jitters` al reconocer de 10 a 1-2, **solo después de medir
   precisión con fotos reales** (el registro inicial sigue en 25).
6. Escaneo por cédula: una consulta indexada + un insert, respuesta
   mínima. Cada registro de ingreso lleva un identificador generado por el
   kiosco, para que un reintento o una sincronización del modo
   contingencia nunca lo duplique.

**Formularios**
7. Página del formulario desde la caché de Cloudflare (se purga al
   editar); pre-llenado y cupos restantes por llamadas pequeñas, con caché
   de pocos segundos o contador.
8. Envío: dentro del bloqueo del cupo solo verificar, insertar y
   confirmar; todo lo demás (correo, escarapela, alimentar la BD del
   evento) a la cola. La pantalla de confirmación muestra y deja descargar
   la escarapela al instante.
9. Si la base no responde, el navegador conserva lo escrito y reintenta
   solo con la misma clave de envío (sin duplicar), mostrando "estamos
   procesando tu inscripción".
10. Pagos: además de los webhooks de Wompi, una conciliación periódica que
    consulta a Wompi por referencia, por si un webhook se perdió durante
    una falla.

**Directorio, reportes, cargas**
11. Directorio paginado e incremental.
12. Reportes Excel en segundo plano (Cloud Run Job), nunca dentro de la
    petición durante un evento.
13. Carga masiva de fotos: subida directa a Cloud Storage con URLs
    firmadas (Cloud Run limita cada petición a 32 MiB) y proceso en
    paralelo como Cloud Run Job. Los hilos en segundo plano de hoy
    (`app/bulk_jobs.py`) no sirven en Cloud Run, porque ahí la CPU se
    reduce cuando la petición termina.

**Base de datos y arranque**
14. Conexión por el pooler de Neon (modo transacción: nada de `SET` de
    sesión, tablas temporales ni `LISTEN/NOTIFY` en la app; migraciones
    por conexión directa), reintentos automáticos de reconexión, índices
    para cédula dentro de evento, registros por evento y formularios.
15. `face_recognition`/dlib importado solo en el servicio "biometria".

## 9. Modo contingencia del kiosco (la pieza que evita que se caiga la noche)

- Antes y durante el evento, cada kiosco descarga el roster del evento y
  lo guarda en el dispositivo, con lo mínimo: una huella (hash con sal del
  evento) de la cédula y del código QR de la escarapela, nombre para
  mostrar, categoría y estado. Nada de fotos ni encodings.
- Si el servidor no responde por unos segundos, el kiosco pasa solo a
  contingencia (indicador visible para el operador): valida cédula y QR
  contra la copia local, registra el ingreso en una cola local y sigue.
- Al volver la conexión, sincroniza la cola sin duplicar (identificador
  por registro) y marca los casos a revisar (misma persona ingresada en
  dos kioscos durante la desconexión).
- El reconocimiento facial no funciona sin conexión en esta versión: en
  contingencia, esa estación pasa a cédula/QR. Registros nuevos en puerta
  se guardan localmente sin rostro y se completan al sincronizar.
- La copia local se borra al finalizar el evento. Debe quedar reflejado en
  la política de privacidad.

## 10. Riesgos fuera de la nube

- **Internet del recinto:** el modo contingencia lo cubre, pero conviene
  igual una conexión de respaldo 4G/5G por evento.
- **Correo:** Exchange Online limita cada buzón a **30 mensajes por minuto
  y 10.000 destinatarios por día** (5.000 correos ≈ 2,8 horas). Opción
  gratis: escarapela visible y descargable al instante + correos por cola
  a ese ritmo. Opción casi gratis: Amazon SES (~US$0,10 por 1.000).
- **Wompi:** su disponibilidad no depende de Golden; cubierto con
  reintentos, idempotencia y conciliación (§8, puntos 9-10).
- **Neon como nuevo encargado de datos personales:** debe agregarse a la
  política de privacidad junto a Google, Wompi y Microsoft. Los encodings
  faciales siguen cifrados con la llave de la app.

## 11. Plan por fases

### Fase 0 — Código, sobre la VM actual (US$0 adicionales)
Prueba de carga de línea base (nunca contra producción) → puntos 1-12 y
14-15 de §8 que no dependan de Cloud Run → repetir la prueba y comparar.
Esta fase sola ya evita la mayoría de caídas.

### Fase 1 — Datos fuera de la VM
- Medir latencia real entre Google `us-east4` y Neon `aws-us-east-1`.
- Fotos, adjuntos y archivos → Cloud Storage.
- Base de datos → Neon (volcado y restauración en una ventana sin
  eventos), pooler, topes, backup diario propio a Cloud Storage,
  restauración **probada**.
- Alertas de presupuesto y chequeos de disponibilidad.

### Fase 2 — App a Cloud Run y apagado de la VM
- `Dockerfile`, tres servicios, escalado a cero, topes, precalentamiento
  automático (Cloud Run + Neon).
- Despliegue desde GitHub Actions sin llaves (Workload Identity
  Federation), congelamiento en eventos, migraciones como Cloud Run Job,
  vuelta atrás documentada. Reemplaza el runner self-hosted.
- Cargas masivas y reportes como Cloud Run Jobs; correos por Cloud Tasks.
- Dos semanas estables → última instantánea de la VM → apagarla.

### Fase 3 — Modo contingencia del kiosco (§9)

### Fase 4 — Demostrarlo: prueba de carga + simulacro de fallas
Contra staging, con todos los escenarios al mismo tiempo:

| Escenario | Criterio de aprobado |
|---|---|
| Formularios | 10.000 usuarios virtuales abren el formulario en 60 s y 5.000 lo envían en 120 s: 0 errores 5xx, p95 del envío < 2 s, cero sobrecupos, cero duplicados |
| Escaneo por cédula | 200 escaneos concurrentes sostenidos 30 min (~57/s): p95 < 500 ms, 0 errores |
| Escaneo facial | Objetivo a fijar tras medir el costo real en Fase 0; referencia: 30/s con p95 < 2 s |
| Aislamiento | Durante el pico de formularios, la latencia de escaneo no sube más de 20% |
| **Simulacro 1** | Se elimina una instancia de Cloud Run a mitad de la prueba: cero ingresos perdidos |
| **Simulacro 2** | Se reinicia el cómputo de Neon a mitad de la prueba: los kioscos siguen (contingencia si hace falta), los formularios reintentan y ninguna inscripción se pierde ni se duplica |
| **Simulacro 3** | Se corta la red de un kiosco 10 minutos: sigue admitiendo por cédula/QR y sincroniza sin duplicados |
| Costo | La prueba completa cuesta lo esperado para una noche pesada (§6) |

Hasta que la Fase 4 no pase, la respuesta honesta a "¿aguanta una noche
de 6 eventos?" es "todavía no está demostrado".

## 12. Si prefieren no sumar un segundo proveedor

Alternativa 100% Google: Postgres en una VM pequeña dentro de un **grupo
de instancias administrado con estado, tamaño 1, con disco regional**
(copiado en dos zonas) y verificación de salud: si la VM o su zona
fallan, Google crea otra en la otra zona con el mismo disco en ~2-5
minutos. Cuesta ~US$28-33/mes solo la base (no es por uso), así que el
total rondaría o pasaría los US$40, y la recuperación es en minutos, no
segundos. Queda como plan de respaldo.

## 13. Impacto en el Sprint 5 (ya en `main`)

Revisado en el código: el cupo con bloqueo, la reserva de 30 minutos
durante el pago y el rechazo de duplicados **ya están implementados**. Lo
que falta está en §8: bloqueo lo más corto posible, cupos restantes sin
contar en cada apertura, cola para lo pesado, reintento idempotente del
lado del navegador y conciliación de pagos con Wompi.

## 14. Salud, estado y diagnóstico (agregado 2026-09-26)

Objetivo: poder ver en cualquier momento qué está funcionando, qué no y
por qué, sin entrar a los servidores. Todo dentro de capas gratuitas.

**En la app (lo construye Claude Code):**
- `GET /healthz` — ¿el proceso está vivo? Sin tocar dependencias, responde
  en milisegundos. Lo usan Cloud Run y los monitores externos.
- `GET /readyz` — ¿puede atender de verdad? Revisa la base de datos (con
  tiempo límite), el almacenamiento y, en "biometria", que el modelo esté
  cargado. Si algo falla responde 503 diciendo qué componente y por qué.
- `GET /api/ops/status` (solo admin+) y una pantalla **"Estado del
  sistema"** en el panel: versión desplegada (commit), latencia de la base
  de datos, conexiones, tareas en cola y la más antigua, tareas fallidas,
  último backup, cargas masivas en curso, eventos en curso y aperturas de
  las próximas 24 h, correos pendientes o fallidos, último webhook de Wompi
  y pagos sin conciliar, errores de los últimos 15 minutos. Cada ítem en
  verde, amarillo o rojo, con el motivo en español y qué hacer.
- `GET /api/ops/deploy-allowed` — para el congelamiento de despliegues.
- Logs estructurados (JSON a la salida estándar, formato que Cloud Logging
  entiende) con un identificador por petición. Todo error inesperado se
  registra con su traza (Error Reporting de Google lo agrupa solo, gratis)
  y al usuario se le muestra un mensaje amable con ese identificador, para
  poder buscar el caso exacto. **Sin datos personales en los logs**
  (cédulas, nombres, correos, encodings enmascarados).

**Fuera de la app (lo configura Juan David, gratis):**
- Chequeo de disponibilidad de Google Cloud Monitoring cada minuto sobre
  `/healthz` y `/readyz` (1 millón de ejecuciones al mes gratis), con
  alertas al correo y a la app de Google Cloud en el celular.
- Un monitor externo independiente (UptimeRobot, plan gratis de 50
  monitores cada 5 minutos, uso comercial permitido): si el problema es de
  Google, el monitoreo de Google también podría fallar.
- Cloud Logging (50 GiB/mes gratis por proyecto) y Error Reporting
  (gratis) quedan activos automáticamente con Cloud Run.

## 15. Actualización tras la Fase 0 (2026-09-27)

**Resultados de la Fase 0** (rama `perf/fase0-carga`, prueba local con 8.000
personas sintéticas; detalle en `docs/14_FASE0_RESULTADOS.md` del repo):

| | Antes | Después |
|---|---|---|
| Formulario | 0 envíos (servidor colgado) | 4.768 envíos, 0 fallos, p95 380 ms |
| Cédula (meta ~57/s) | 0,8/s | 56/s, p50 7 ms |
| Directorio de 8.000 | 36 s | 1,1 s |
| Facial | ~10 s por escaneo | ~2,4 s, en proceso aparte (0,4-0,7/s por proceso) |

Hallazgos nuevos de Claude Code: el servidor se colgaba con ~30 envíos
simultáneos (conexiones del pool retenidas mientras se espera el cuerpo de
la petición) y dlib retiene el GIL (un escaneo facial congelaba todo). Ambos
resueltos. **El facial sigue siendo el cuello de botella**: depende de bajar
`num_jitters` (~0,46 s por jitter; con 1-2 sería 5-8 veces más rápido),
pendiente de medir precisión con fotos reales (`RECOGNITION_JITTERS` en el
entorno, sin tocar código).

**Decisiones nuevas para la migración:**

1. **Región de Cloud Run: `us-east4` (Virginia del Norte) — decisión de Juan David, 2026-09-29.** Junto a Neon (AWS us-east-1). Corrige lo que decía este punto antes: `us-east1` y `us-east4`
   son ambas de Nivel 1 (mismo precio de Cloud Run, verificado en la lista oficial de ubicaciones). Todo lo regional (servicios, Jobs, Artifact Registry, Cloud Tasks, Scheduler y bucket)
   va en la misma región. La región es un parámetro (`deploy/gcp/config.sh`); el traslado de staging y el arranque de producción: `docs/15_MIGRACION.md`, «Mover a otra región».

| Medida (Cloud Run → Neon, conexiones calientes, `scripts/measure_db_latency.py`) | us-east1 | us-east4 |
|---|---:|---:|
| Una consulta con la conexión abierta (1 ida y vuelta, RTT) | **15,1 ms** | **4,9 ms** |
| Conexión nueva (TCP + TLS + autenticación) | 107 ms | 49 ms |
| Transacción de 3 sentencias con commit | 75,5 ms | 23,8 ms |
| Bloqueo del cupo de UN formulario ≈ 3 RTT (`form_reserve_slot` + `INSERT` + `COMMIT`) | ≈ 45 ms | ≈ 15 ms |
| Envíos por segundo por formulario que permite ese bloqueo (1 / duración) | **≈ 22/s** | **≈ 68/s** |
| Meta de la Fase 4: 5.000 envíos en 120 s | ~42/s: NO alcanza | ~42/s: cumple con ~1,6× de margen |

**Por qué el cupo decide la región.** El cupo atómico ya va en UNA sentencia (`form_reserve_slot`), pero la fila del formulario queda bloqueada hasta el `COMMIT`: mientras tanto corren esa función, el
`INSERT` y el `COMMIT`, o sea ~3 idas y vueltas con el bloqueo tomado. Los envíos de UN mismo formulario se serializan por ese bloqueo, así que su tope es 1 / (3 × RTT): con 15,1 ms de RTT son ~22 envíos/s
(la meta de 42/s se rompería con cola y `p95 > 2 s`); con 4,9 ms son ~68/s. Cota pesimista: si se contara la transacción completa de 3 sentencias medida arriba (~5 RTT, con el inicio de la transacción), serían
13/s en us-east1 y 42/s en us-east4 — justo la meta, sin margen; el número real se confirma con la prueba de carga de la Fase 4 (formularios) en la región nueva. Además `/ready` mide dos idas y vueltas (el `pre_ping` del pool
+ la consulta): 2 × 15,1 ≈ 30 ms de los 43-46 ms vistos en staging; el resto no se descompuso (la medida `engine_checkout_select1_like_ready` del mismo script lo separa).

2. **Cupo en una sola sentencia SQL.** Hoy el bloqueo de la fila del
   formulario dura varias idas y vueltas a la base. Con la base a 10-15 ms,
   eso limitaría cada formulario a ~25 envíos/s. El control de cupo debe
   hacerse en una sola sentencia atómica (o función en la base), para que
   el bloqueo dure una sola ida y vuelta.
3. **Dominio propio frente a Cloud Run: Firebase Hosting.** Verificado: el
   balanceador de carga de Google (la opción "recomendada") tiene un costo
   fijo que rompe el presupuesto; el mapeo de dominios de Cloud Run está en
   vista previa y Google dice que no es para producción; y el plan gratis de
   Cloudflare **no** permite cambiar el encabezado Host, que Cloud Run
   necesita, así que no puede apuntar directo a Cloud Run. Firebase Hosting
   (del mismo Google, cobro por uso, certificado SSL incluido) recibe el
   dominio y reenvía a Cloud Run; además sirve los archivos estáticos desde
   su propia CDN. Cloudflare queda como DNS de esos subdominios. Alternativa
   si Firebase Hosting no encaja (límite de tiempo por petición, etc.): un
   Cloudflare Worker como proxy (~US$5/mes).
4. **Prueba de carga de la Fase 4 distribuida:** desde un solo equipo solo
   se sostuvieron ~108 envíos/s; la prueba de 10.000/5.000 se corre desde
   varias instancias temporales (por ejemplo Cloud Run Jobs) contra staging.
5. **Entorno de staging casi gratis:** servicios `*-staging` en Cloud Run que
   escalan a cero + una rama `staging` de Neon (copia instantánea de la base
   que solo cobra cómputo mientras se usa).

## 16. Plan de ejecución acordado (2026-09-27): 3 semanas sin eventos

Sin eventos en las próximas 3 semanas, se hace la migración completa ya,
con nube y código en paralelo (los recursos de Google se crean con el
script que escribe Claude Code, no a mano):

- **Semana 1:** cuenta y proyecto de Neon + rama `staging` (manual);
  merge de la Fase 0 a `main` (su despliegue en la VM sirve de prueba real
  en Linux de Gunicorn con 3 procesos); Claude Code construye las Fases 1-2.
- **Semana 2:** correr `deploy/gcp/bootstrap.sh` en Cloud Shell, activar
  Firebase Hosting, desplegar staging con copia de la base, medir latencia
  (decidir `us-east1` o `us-east4`), prueba de carga de 10.000/5.000 y
  simulacros de falla. En paralelo, Claude Code construye la Fase 3 (modo
  contingencia) en otra rama.
- **Semana 3:** día del cambio con el runbook (VM apagada, no borrada, como
  respaldo); prueba de la Fase 3 con un evento simulado.
- **Después:** borrar la VM, liberar la IP fija, cerrar la cuenta de
  facturación "Pago de Firebase".

## 17. Qué hace Claude Code y qué hace Juan David

- **Claude Code:** todo el código de las fases 0-3, `Dockerfile`, pruebas
  de carga y simulacros, flujo de despliegue, y documentación con los
  comandos exactos para crear cada recurso. Reglas de siempre: rama
  propia, sin push a `main` ni despliegue sin autorización, decide y
  documenta ante ambigüedades. Pruebas de carga **nunca** contra
  producción. Todo recurso que pueda generar costo lleva su tope desde el
  primer commit.
- **Juan David:** crear la cuenta de Neon (plan Launch) y los recursos de
  Google, alertas de presupuesto, confirmar región y tipo de la VM actual,
  decidir correo (cola gratis vs. SES), actualizar la política de
  privacidad con Neon, y garantizar dispositivo de repuesto y conexión de
  respaldo en cada evento.

## Fuentes

- Google Cloud Observability — capas gratuitas:
  https://cloud.google.com/products/observability/pricing
- UptimeRobot — plan gratis y uso comercial:
  https://flarewarden.com/insights/uptimerobot-free-plan-commercial-use
- Cloud Run — ubicaciones y niveles de precio: https://docs.cloud.google.com/run/docs/locations
- Cloud Run — dominios personalizados: https://docs.cloud.google.com/run/docs/mapping-custom-domains
- Cloudflare — disponibilidad de Origin Rules por plan: https://developers.cloudflare.com/rules/origin-rules/
- Neon — precios: https://neon.com/pricing
- Neon — regiones: https://neon.com/docs/introduction/regions
- Neon — alta disponibilidad y tiempos de recuperación:
  https://neon.com/docs/introduction/high-availability
- Neon — apagado automático (reactivación en cientos de milisegundos):
  https://neon.com/docs/introduction/scale-to-zero
- Neon — pooler de conexiones: https://neon.com/docs/connect/connection-pooling
- Cloud Run — SLA (99,95%): https://cloud.google.com/run/sla
- Cloud Run — precios: https://cloud.google.com/run/pricing
- Cloud Run — límites: https://docs.cloud.google.com/run/quotas
- Google Cloud — recursos regionales en varias zonas:
  https://docs.cloud.google.com/architecture/infra-reliability-guide/building-blocks
- e2-medium US$24,46/mes:
  https://www.economize.cloud/resources/gcp/pricing/compute-engine/e2-medium/
- `face_recognition` — `num_jitters`:
  https://face-recognition.readthedocs.io/en/latest/_modules/face_recognition/api.html
- Exchange Online — límites de envío:
  https://learn.microsoft.com/en-us/office365/servicedescriptions/exchange-online-service-description/exchange-online-limits
