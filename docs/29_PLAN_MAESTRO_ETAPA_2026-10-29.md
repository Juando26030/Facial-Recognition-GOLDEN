# 29 · Plan maestro de la etapa «Después del piloto» — GoldenWeb 2.0

Aprobado por Juan David el 29-oct-2026. **Este documento es la guía de trabajo hasta cerrar la etapa.** Reemplaza, para esta etapa, el orden de prioridades anterior. Lo que no está aquí no se trabaja sin que Juan David lo apruebe y se agregue.

---

## 0. Protocolo de trabajo (obligatorio)

1. **Una fase a la vez, en orden.** No se empieza una fase hasta que la anterior cumpla TODOS sus criterios de «listo» y Juan David lo confirme por escrito. Excepciones permitidas solo si el plan las marca (Fase 9 intercalada, evaluación del CRM en paralelo).
2. **Las dudas se preguntan al empezar cada fase, no antes.** Cada fase trae su lista de «Preguntas al iniciar». Claude las hace en ese momento, una fase a la vez, y las respuestas se anotan en el «Registro de decisiones» (sección 11) para que no se pierdan en la conversación.
3. **Al cerrar cada fase** Claude actualiza el tablero (sección 12), anota las decisiones tomadas y confirma con Juan David el paso a la siguiente.
4. **Una entrega a producción por semana como máximo.** Siempre: rama (no `main`) → staging → pruebas → orden escrita de Juan David «DESPLIEGA PRODUCCIÓN» → despliegue con la receta de siempre (copia de Neon, PR con «Create a merge commit» + `[skip ci]`, despliegue manual, verificación posterior, punto de retorno anotado). Nunca con un evento «En Proceso» ni a punto de abrir. Nunca `force`.
5. **No se toca** lo fijado en `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` (página 62 × 99,8 mm, imagen ≤ 96 mm, margen izquierdo 0,5 mm, marca de fin, Chrome con su cuadro normal, nunca `--kiosk-printing`).
6. **Ninguna funcionalidad se esconde ni se elimina por simplificar.** Se simplifica ordenando, guiando y ayudando (ver sección 2).
7. **Ante algo no previsto** que cambie el alcance: se anota en la sección 17 («Cambios al plan») y se pregunta a Juan David.
8. **Seguridad en cada fase (añadido 29-oct):** cada fase tiene su «chequeo de seguridad» según la tabla de la sección 4d. Una fase no se cierra con hallazgos críticos o altos abiertos.
9. **Pruebas de ataque solo contra staging con datos ficticios,** nunca contra producción (ver 4c).

---

## 1. Punto de partida (29-oct-2026)

- Producción (`app.golden-eventos.com`) corre `main` = `b36bf92ead480fec92f267d3c29d67e286294baf`, migraciones hasta 0075, modo sin conexión encendido.
- El piloto del 30-oct fue un éxito. Se corrió por error en staging y se exportó e importó a producción con el módulo de exportar/importar eventos. El evento **no usó reconocimiento facial** (no hay biometría que purgar).
- Retroalimentación del piloto: bien en general; los digitadores se demoraban porque no era claro dónde buscar la cédula, había dos buscadores (cédula y nombre), imprimir no era obvio, la autoimpresión y el autorregistro tenían fallos, los campos opcionales quedaban abajo (había que bajar y volver a subir), y el asistente recién creado no aparecía de primero en el directorio en vivo.
- Corregidos y estables en producción antes de esta etapa: impresión compartida (anfitrión y sesión única, detección de impresora, márgenes iguales entre celular y computador, imprimir pendientes en una sola ventana, una sola ventana de impresión).

---

## 2. Principios de diseño y acceso (valen para TODA la plataforma)

- **Prueba de los 5 segundos:** una persona nueva sabe qué hacer en una pantalla sin leer.
- **Una tarea por pantalla;** asistentes por pasos («Paso 2 de 5»); botón principal único y claro.
- **Todo accesible a un clic;** lo frecuente, grande y a la vista; lo avanzado, a un clic, nunca oculto.
- **Buscador «¿qué quieres hacer?»** que encuentra cualquier función por nombre.
- **Ayuda en contexto:** «?» en cada pantalla, con dibujo o animación corta; recorrido la primera vez.
- **Errores que dicen qué hacer,** no qué falló.
- **Tema claro por defecto; oscuro opcional POR DISPOSITIVO** (no por cuenta). Las escarapelas y sus plantillas nunca cambian de tema.
- Los principios estéticos y de acceso aplican **a todos los roles, incluido super_admin.** La simplificación de lenguaje y guías es para digitadores, clientes, coordinadores y comerciales.
- Contraste ≥ 4,5:1, tamaño táctil ≥ 44 px en pantallas táctiles, fuente de la app (Agrandir; la licencia web la gestiona Juan David).
- Inspiración: Conventus Portal (un mosaico grande por tarea, minimalismo), y prácticas actuales de check-in (QR dinámico, carriles de rostro, kioscos de autoatención, tarjeta en Wallet, mensajería).

---

## 3. Decisiones ya tomadas

| # | Decisión |
|---|---|
| D1 | Tema claro por defecto, oscuro por dispositivo. |
| D2 | Un solo buscador inteligente que detecta cédula, nombre, empresa y código del lector. |
| D3 | Lo recién registrado aparece de primero, resaltado, en una **cola compartida por evento** (no por usuario ni dispositivo). |
| D4 | Reimpresión configurable por evento: por defecto habilitada con aviso «ya se imprimió»; el admin puede deshabilitarla; si está deshabilitada, el digitador puede pedir permiso de emergencia. **Las solicitudes y su aprobación llegan por correo** (al coordinador del evento y al super_admin), no solo por la app. |
| D5 | Borrar = archivar; el borrado definitivo solo lo hace super_admin con confirmación. El registro de consentimientos no se borra. |
| D6 | Credenciales de temporales: usuario = cédula, contraseña = cédula. Acceso solo a ese evento; vence al finalizarlo. Bloqueo temporal tras intentos fallidos, visible y desbloqueable por el coordinador. Exigir cambio de contraseña en el primer ingreso: opción apagada por defecto. |
| D7 | Compromiso digital del digitador: formulario web propio con plantilla fija, firma dibujada, vigencia de 30 días; sin firma vigente no digita ni se le asigna evento. |
| D8 | Formulario de persona diseñado por el admin con el motor de formularios web (sin la parte pública). |
| D9 | L7 (borrado de datos de contacto a los 90 días de cerrado el evento) se hace en diciembre de 2026. Es la única fecha dura, por la política de privacidad. |
| D10 | El CRM actual es **SugarCRM (versión antigua)**. Es de uso interno de Golden y **no irá dentro del SaaS**; la licencia del CRM nuevo no impide el uso interno. |
| D11 | Orden de fases: 0A, 0B, 0C, 1A, 1B, 2, 3, 4, 5, 6, 7, 8, 9, 10 (con las intercalaciones indicadas). |
| D12 | **Antes de construir nada nuevo se limpia y organiza el repositorio (0B) y se hace una línea base de seguridad (0C).** |
| D13 | **La seguridad NO va de última: se hace una vez al sanear el código actual y se repite en cada fase según la sección 4d.** |
| D14 | **Las pruebas de ataque (agentes de IA, Strix y similares) se hacen solo contra staging con datos ficticios, nunca contra producción.** |

---

## 4. Fase 0A · Cierre del piloto (1–2 días)

**Objetivo:** dejar limpio el piloto y saber con certeza el estado real del producto.

**Alcance**
- Juan David: finalizar el evento en producción (el reloj de L7 corre desde su cierre) y borrar de staging la copia del evento real.
- Bot, solo lectura: reconciliar los 41 puntos pendientes de la lista de Juan David contra `main` (hecho / sin integrar / por hacer) y entregar la tabla.
- Bot: reproducir y documentar los fallos de autoimpresión y autorregistro **antes de tocar código**, con la matriz:

| Eje | Casos |
|---|---|
| Cómo se ingresa | lector de código · Enter con escritura manual · clic en un resultado |
| Dónde se guarda | acreditar desde el directorio · editar y guardar · «registrar nuevo» |
| Configuración | solo autorregistro · solo autoimpresión · ambos activos a la vez (el caso que falló) |
| Entorno | con red · sin red · impresión local · impresión compartida |

**Listo cuando:** evento finalizado en producción; staging sin datos reales; tabla de estado de los 41 puntos entregada; tabla «funciona / falla / por qué» de la matriz entregada.

**Preguntas al iniciar:** ninguna pendiente (ya se respondió qué fallaba).

---

## 4b. Fase 0B · Limpieza y orden del repositorio (3–5 días)

**Objetivo:** dejar un repo limpio y ordenado, sin cambiar el comportamiento de la app.

**Regla de oro:** cambios que no alteran comportamiento. La red de seguridad es la suite completa de pruebas (la misma cantidad, ninguna debilitada o borrada para que pase), las pruebas de JS y los smoke tests. **No se toca** el código de impresión fijado (parámetros inamovibles), los textos legales literales de la auditora (`app/legal_texts_data.py`) ni la lógica de consentimiento y biometría, salvo movimientos mecánicos con pruebas. Un PR por categoría.

**Alcance**
1. **Inventario de solo lectura** (primero se mide, luego se borra): código muerto (variables e importaciones sin usar, rutas sin uso, funciones sin llamadas), plantillas y archivos estáticos sin referencias, scripts obsoletos, dependencias sin usar, pruebas duplicadas, binarios o archivos generados dentro del repo, duplicados de documentos (por ejemplo hay dos `13_…` y dos `18_…` en `docs/`).
2. **Ramas:** listar todas (`producto/*`, `fix/*`, `ux/*`, `integracion/*`, `archivo/*`, `corte/*`) y clasificarlas en fusionadas, abandonadas o vigentes. Antes de borrar cualquiera se deja una **etiqueta de archivo** para poder recuperarla, y se borra solo la lista que Juan David apruebe.
3. **Historial:** escanear secretos en TODO el historial de git, no solo en el código actual (documentos antiguos decían que el repo era público). Si aparece un secreto, hay que rotarlo; esa rotación la hace Juan David.
4. **Organización:** estructura de carpetas y nombres, README raíz y `CLAUDE.md` al día, índice de `docs/`, scripts agrupados por tema. Los archivos muy largos (por ejemplo `app/routers/api.py`, `static/js/shared-print.js`) se dividen solo de forma mecánica, en PRs separados, sin cambiar lógica.
5. **Calidad:** hoy el CI revisa con `ruff` solo los archivos tocados; pasa a revisar **todo el repo**, con correcciones automáticas seguras, y se agrega `pre-commit`.
6. **Dependencias:** actualizar solo lo que tenga parches de seguridad, sin saltos mayores de versión.
7. **Código de la VM antigua** (`deploy/` de la VM, Gunicorn, Nginx, `deploy.yml`): se marca como heredado y no se borra hasta que Juan David confirme que la VM está cerrada.

**Listo cuando:** la suite pasa con la misma cantidad de pruebas; los smoke tests dan igual en staging; ramas limpias con sus etiquetas de archivo; README e índice de `docs/` al día; `ruff` pasa sobre todo el repo; el historial no tiene secretos (o los hallados ya están rotados); lista de lo borrado entregada.

**Entrega:** como cambia el código, sale en **una** entrega a producción, tras staging y con tu «DESPLIEGA PRODUCCIÓN». Lo que solo es documentación o ramas no requiere despliegue.

**Preguntas al iniciar:** la lista de ramas a borrar (se presenta clasificada); si la VM antigua ya se puede dar por cerrada.

---

## 4c. Fase 0C · Línea base de seguridad (1–1,5 semanas)

**Objetivo:** encontrar y corregir las vulnerabilidades del código actual antes de construir encima.

**Por qué después de limpiar y antes de construir** (práctica estándar de «seguridad desde el inicio», OWASP y DevSecOps): probar el código ya depurado evita ruido de código muerto, y corregir los problemas antes de agregar fases evita que cada fase herede los mismos errores. Si durante la limpieza aparece algo crítico (por ejemplo un secreto en el historial), se atiende de inmediato sin esperar a esta fase.

**Capas (en este orden)**
1. **Revisión del código por agentes de Claude, caja blanca y solo lectura.** Foco: autenticación y sesiones, permisos por rol y aislamiento entre clientes y eventos (el riesgo de ver o editar datos de otro evento), CSRF y cookies, subida de archivos y URLs firmadas, inyección (SQL, plantillas, XSS en el JS), SSRF, endpoints `/internal`, límites de intentos, tokens de los enlaces de aceptación, webhook de pagos, datos personales en logs, cifrado de rostros y registro de consentimientos.
2. **Escáneres automáticos:** análisis estático (Semgrep o Bandit), dependencias vulnerables (`pip-audit`), secretos (`gitleaks`), imagen del contenedor (Trivy) y cabeceras web (OWASP ZAP en modo básico).
3. **Prueba dinámica con agentes que atacan la app en marcha** (caja negra): **Strix** (herramienta de código abierto con agentes de IA que ataca la aplicación y valida cada hallazgo con una prueba de concepto) y OWASP ZAP. Condiciones obligatorias:
   - solo contra **staging, con datos ficticios**; nunca producción (estas herramientas ejecutan ataques reales y pueden alterar datos o tirar el servicio);
   - antes, una **rama de respaldo de Neon** de staging;
   - correo, SMS, WhatsApp y pagos en modo de prueba o apagados, para que no salga nada real;
   - una **clave del proveedor de IA exclusiva, con límite de gasto**, guardada como secreto (la crea Juan David; nunca en el repo ni en el chat), porque el código y las respuestas de la app viajan a ese proveedor;
   - ejecución aislada (contenedor) y no en una máquina con acceso a producción; revisar el instalador antes de correrlo;
   - cuentas de prueba de cada rol, para atacar desde cada perfil;
   - confirmar la licencia de Strix en su repositorio antes de usarlo, y revisar cualquier arreglo que proponga antes de aceptarlo.
4. **Revisión de infraestructura:** permisos de Cloud Run y de las cuentas de servicio, buckets, Secret Manager, Firebase, Cloudflare y roles de Neon. Los comandos de nube los corre Juan David.

**Reporte y severidades:** cada hallazgo con severidad (crítica, alta, media, baja), prueba de concepto y arreglo propuesto. **Críticas y altas:** se corrigen antes de seguir a la Fase 1A (con la vía de corrección urgente si afectan a producción hoy y Juan David la autoriza). **Medias:** dentro de las fases siguientes, con fecha. **Bajas:** al backlog. Todo lo corregido se vuelve a probar.

**Listo cuando:** reporte entregado; cero críticas y cero altas abiertas; medias con fecha; nueva prueba pasada; el CI ejecuta en cada PR los escáneres automáticos (análisis estático, dependencias y secretos).

**Preguntas al iniciar:** proveedor y tope de gasto de la clave de IA para las pruebas dinámicas; ventana de fechas para las pruebas; si quiere además una prueba de penetración humana externa.

---

## 4d. Seguridad continua por fase

| Cuándo | Qué se hace |
|---|---|
| **En cada PR (automático)** | Análisis estático, dependencias vulnerables y secretos; los hallazgos críticos o altos bloquean la fusión. |
| **Al cerrar 1A, 1B y 2** | Revisión de seguridad del diff por agentes + ZAP básico. En 1B, **prueba dirigida del enlace de aprobación por correo** (un solo uso, caducidad, no adivinable). |
| **Al cerrar 3, 4, 5, 7 y 10** | **Prueba dinámica completa en staging** (Strix + ZAP), porque tocan permisos, cuentas, credenciales, datos y endpoints públicos. En 4, foco en el bloqueo por intentos (las credenciales cédula/cédula) y en la firma del compromiso; en 3, foco en que el archivado y el borrado respeten los permisos por rol. |
| **Al cerrar 6** | Revisión y prueba de la sincronización del servidor local. |
| **Antes de ofrecer el SaaS** | Prueba completa + **prueba de penetración humana externa (recomendada)** + lista de verificación OWASP ASVS nivel 2. Después, repetir cada 6 meses o ante cambios grandes. |

Los hallazgos siguen la misma regla de severidad de 0C. Los incidentes reales siguen el protocolo de incidentes ya aprobado por la auditora (doc 18).

---

## 5. Fase 1A · Puerta rápida (1,5–2 semanas; primera entrega a producción)

**Objetivo:** que un digitador nuevo registre sin ayuda y rápido.

**Alcance**
1. **Buscador único inteligente** (cédula, nombre, empresa, código del lector); autofoco; cada resultado indica por qué coincidió; funciona igual sin red (la cédula se busca por coincidencia exacta, por el diseño de privacidad).
2. **Pantalla sin subir y bajar:** búsqueda compacta y fija arriba, directorio en vivo ocupando el resto, explicaciones en un «?» con dibujo o animación.
3. **Cola compartida de lo recién registrado:** si el computador X registra a Pepito, Pepito aparece de primero en el computador Y. Resaltado. Sin red, cada equipo ve lo suyo al momento y recibe lo de los demás al sincronizar; dos equipos desconectados a la vez no se ven entre sí (se avisa en pantalla).
4. **Autoimpresión y autorregistro corregidos** según la matriz de la Fase 0. Preferir una sola cola de acciones por persona antes que parchar cada caso. Pruebas automáticas y prueba física con la Brother.
5. **Formulario de persona diseñado por el admin:** reutilizar el motor de formularios web (sin parte pública): orden, columnas, grupos, obligatorios arriba y a la vista. Se usa al crear y al editar personas. **La definición debe viajar versionada en la copia local** para que alta y edición funcionen igual sin red. Va detrás de un interruptor y con pruebas sin red antes de salir.
6. **Medición:** tiempo por registro (con los registros de acceso) antes y después; prueba con 2 digitadores que nunca hayan visto la pantalla.

**Listo cuando:** un digitador nuevo busca, registra y (si aplica) imprime sin preguntar; autoimpresión y autorregistro pasan toda la matriz, incluido «ambos activos»; lo recién registrado aparece de primero en otro equipo; el tiempo por registro baja de forma medible; sin regresiones en la suite de pruebas.

**Preguntas al iniciar:** cuántos campos suele tener el formulario de persona y cuáles son los obligatorios típicos (para el diseño por defecto).

**Riesgos:** el formulario configurable toca lo que viaja a los dispositivos sin red; la cola compartida requiere ordenar por hora del servidor.

---

## 6. Fase 1B · Impresión con permisos (1 semana)

**Alcance**
- Imprimir con un botón y un estado visible: «imprimiendo», «lista», o error con qué hacer.
- **Reimpresión configurable por evento (Parámetros del evento):**
  - Por defecto habilitada; si la persona ya se imprimió, solo avisa «ya se imprimió».
  - El admin puede deshabilitarla por completo.
  - Si está deshabilitada y el digitador lo intenta: «No se puede reimprimir» y debajo «¿Es una emergencia autorizada? Solicitar permiso».
  - Al solicitar, se envía **un correo** al coordinador del evento y al super_admin con un enlace seguro de un solo uso para aprobar o negar (también visible dentro de la app). Al aprobar, se reimprime una sola vez y el permiso caduca.
  - Cada solicitud, aprobación, negación y reimpresión queda registrada (quién, cuándo, a quién).
  - Requiere red; sin conexión el aviso lo dice.

**Listo cuando:** las tres configuraciones (habilitada, deshabilitada, deshabilitada con permiso) funcionan con la Brother; el correo llega y el enlace aprueba una sola vez; el registro de auditoría muestra la cadena completa.

**Preguntas al iniciar:** tiempo de vigencia del permiso de reimpresión (propuesto: 15 minutos); texto del correo.

---

## 7. Fase 2 · Cimientos de diseño y calendario (2–3 semanas)

**Alcance**
- Sistema de diseño único: colores, tipografía, escala, iconos SVG, componentes, textos. Reutilizar la rama `ux/fase1-visual` en lo que sirva.
- Tema claro por defecto, oscuro por dispositivo.
- Inicio por rol que ordena sin esconder; mosaicos grandes por tarea.
- Buscador «¿qué quieres hacer?».
- Ayudas animadas y recorrido la primera vez.
- Parámetros del evento en pestañas con un Guardar por pestaña; Privacidad aparte con acciones destructivas en rojo.
- **Rediseño del calendario (visual y de contenido):** qué información sale en cada evento, cómo se ve cada estado, filtros por cliente, ciudad, comercial y estado. Los campos nuevos que muestre dependen de la ficha del evento (Fase 5).
- Los principios aplican también al super_admin.

**Listo cuando:** pantallas principales de cada rol rediseñadas; prueba de usabilidad con personas nuevas; contraste y tamaños táctiles verificados; tema por dispositivo funcionando; calendario nuevo aprobado por Juan David.

**Preguntas al iniciar:** los «3 botones por rol» de cada inicio (digitador, coordinador, comercial) y qué información quiere ver cada rol en el calendario.

---

## 8. Fase 3 · CRUD completo (auditoría 2–3 días; oleadas 2–3 semanas)

**Alcance**
- Auditoría de solo lectura: matriz de cada entidad (clientes, usuarios del personal, eventos, personas, categorías, plantillas, formularios, áreas, inventario, premios, etc.) contra crear / ver / editar / archivar / borrar definitivo, por rol.
- Implementación por oleadas, empezando por clientes y usuarios del personal.
- Archivar por defecto; definitivo solo super_admin con confirmación y registro.
- **L7 en diciembre** (intercalado): borrado de datos de contacto a los 90 días de cerrado el evento, según la política de privacidad.

**Listo cuando:** matriz completa sin celdas «no existe» donde debería existir; pruebas de permisos por rol; L7 en producción con su prueba.

**Preguntas al iniciar:** qué roles pueden editar y archivar cada entidad (se propone una tabla y Juan David la ajusta).

---

## 9. Fase 4 · Equipo del evento (3–4 semanas)

**Alcance**
- Carga masiva con plantilla de Excel: cédula, nombre, teléfono, rol (digitador o cliente); crea las cuentas y las asigna al evento automáticamente. Cédula repetida: se reutiliza la persona y solo se asigna. Resultado por fila (creado / ya existía / error con motivo).
- Alta uno por uno con lectura de cédula nueva y vieja.
- Autorregistro por enlace para cliente y digitador.
- Credenciales según D6. Pantalla del coordinador con el estado de cada temporal (activo, sin ingresar, en línea, bloqueado), motivo y hora del bloqueo, y botón «Desbloquear» con registro.
- Opción del admin para exigir cambio de contraseña en el primer ingreso (apagada por defecto).
- Entrega de credenciales: hoja imprimible o envío por WhatsApp/SMS/correo.
- Base de digitadores y clientes descargable solo por admin.
- **Compromiso digital del digitador (D7):** formulario web propio, plantilla fija (Juan David la entrega al llegar a este punto), el digitador lee, confirma y firma dibujando; crea o renueva su perfil; queda asignable por el coordinador. Vence a los 30 días; sin firma vigente no digita ni se le asigna evento. Flujo manual extraordinario a cargo del coordinador con registro de quién lo autorizó. Se guarda el PDF firmado con fecha, hora y huella del contenido. La auditora confirma que sirve como evidencia.

**Listo cuando:** cargar 50 temporales con Excel y verlos asignados; un coordinador desbloquea a un digitador; un digitador con firma vencida no puede digitar y vuelve a poder al renovar.

**Preguntas al iniciar:** **la plantilla del compromiso** (Word); tiempo de bloqueo y número de intentos; canal de entrega de credenciales preferido.

---

## 10. Fase 5 · Crear y configurar eventos (4–5 semanas)

**Alcance (docs/18 y backlog N1, N2, N5)**
- Asistente de creación por pasos, con la ficha configurable dentro.
- Ficha configurable por el admin (campos, tipos, secciones, obligatorios, visibilidad), tipo de evento ampliable, jornada Full o Medio día con hora de inicio y fin, sin «tipo de impresión».
- Estados creados por el admin, con reglas (acceso del cliente, descarga de estadísticas, digitadores temporales, ruleta, registro, inventario…); pantalla en Configuración y selector en el evento.
- Historial de cambios por campo; correo al editar solo por campos clave, a comercial, coordinador, almacén y un rol nuevo «contabilidad».
- Inventario por cantidad con catálogo categorizado y regla de cuadre (suma exacta; sin categorizar en «creado»; todo categorizado para pasar a «en proceso»); reserva con 1 día de anticipación en la misma ciudad y alerta de 1 semana en otra.

**Listo cuando:** crear un evento completo con el asistente; cambiar un campo clave genera el correo correcto; no se puede pasar a «en proceso» con el inventario sin cuadrar.

**Preguntas al iniciar:** **las listas** (tipos de evento, estados, jornadas, campos clave), el catálogo de inventario y los datos para el calendario.

---

## 11. Fase 6 · Operación sin red

**Alcance:** servidor local con sincronización (docs/17); B8 R2–R5 (foto y consentimiento sin red, edición sin red, PIN opcional, dos dispositivos); pruebas en dispositivos reales.

**Listo cuando:** un evento completo se atiende sin internet y al conectarse queda igual en la nube.

**Preguntas al iniciar:** las preguntas abiertas de docs/17.

---

## 12. Fase 7 · Cliente y marca

**Alcance**
- Registro touch.
- Logo por defecto cambiable (subir, previsualizar, restaurar).
- URL limpia de inscripciones.
- **Liberación del evento al cliente:**
  - La comercial marca en el evento un estado o bandera «pagado» o «acuerdo cerrado».
  - Con la bandera positiva se libera el informe final.
  - El cliente solo lo descarga después de responder la encuesta de satisfacción: se exigen las dos condiciones.
  - Encuesta: 5 preguntas Malo/Bueno/Excelente con comentario, probabilidad de recomendar 0–10 y «¿próximo evento? 2 % de descuento».
  - Si el cliente marca interés en otro evento: correo de alerta a la comercial.
  - Depende de los estados de la Fase 5.

**Listo cuando:** un cliente sin encuesta o sin bandera positiva no descarga; con ambas, sí; la alerta llega por correo.

**Preguntas al iniciar:** texto exacto de la encuesta y del correo; nombre del estado o bandera.

---

## 13. Fase 8 · Vanguardia (por demanda, de menor a mayor esfuerzo)

Pantalla de ingreso para TV y estadísticas móviles; turnos y filas; kiosco de autoatención; QR dinámico y tarjeta en Wallet; WhatsApp y SMS masivos; captura de contactos para expositores; pagos con QR. Se elige cuál sigue con Juan David al llegar.

---

## 14. Fase 9 · Plataforma y legal (intercalada, sin bloquear)

Respaldos (copias a las 3 am activas, alerta de borrado masivo, copia semanal fuera del proyecto, copia fuera de línea de la llave de cifrado con `--version-destroy-ttl=7d`); política de privacidad v1.1 (apartado 5-bis del registro sin red); marcador de proveedores (confirmar Google, Neon, Microsoft); L7 se hace en diciembre dentro de la Fase 3.

---

## 15. Fase 10 · CRM integrado (evaluación en paralelo desde la Fase 3; integración después de la Fase 5)

**Contexto:** hoy se usa **SugarCRM (versión antigua)**. El CRM nuevo es para uso interno de Golden y no se incluirá en el SaaS.

**Candidatos** (comparación de Marmelab, enero 2026; el autor es también el equipo de Atomic CRM, hay sesgo):

| Candidato | Licencia | A favor | A cuidar |
|---|---|---|---|
| Twenty | AGPL-3.0 | Moderno, API REST y GraphQL, webhooks, instalación sencilla | SSO y tableros son de pago; AGPL (no aplica al uso interno sin ofrecerlo a terceros; revisar si algún día se abre a clientes externos) |
| Atomic CRM | MIT | Licencia permisiva, pensado como base para construir el propio, buena experiencia móvil | Más una base que un producto terminado |
| Krayin | MIT | Licencia permisiva, API REST | Interfaz lenta y poco clara |

**Alcance**
1. Evaluación en staging de Twenty y Atomic CRM (1 semana): facilidad de uso para la comercial, importación, API.
2. **Importación desde SugarCRM:** Sugar permite exportar listas y reportes a CSV/Excel por módulo (Cuentas, Contactos, Oportunidades, Cotizaciones, Notas…); como es una versión vieja, también puede hacerse con un volcado de su base de datos. Se importa por orden (cuentas → contactos → oportunidades → cotizaciones) guardando la equivalencia de identificadores para no perder las relaciones; las notas y los adjuntos van aparte. Se prueba primero con una muestra y se reporta lo que no entra limpio.
3. Integración en ambos sentidos con GoldenWeb: la comercial gestiona clientes, eventos y cotizaciones en el CRM y se reflejan en la app, y viceversa. Para cada dato se define **una sola fuente de verdad** para evitar pisadas.
4. Objetivo a largo plazo: un CRM propio o adaptado bajo los mismos principios de simplicidad, integrado directamente con la app.
5. Legal: pasar por la auditora el tratamiento de datos de clientes en el sistema adicional.

**Listo cuando:** la comercial gestiona un evento y un cliente en el CRM y se ve en GoldenWeb en segundos, y al revés; una muestra real de SugarCRM importa sin perder relaciones.

**Preguntas al iniciar:** **una exportación de muestra de SugarCRM por módulo (con datos ficticios o recortados) y la versión exacta de Sugar**; qué módulos se usan de verdad; quién gestiona el CRM hoy; dónde está alojado.

---

## 16. Registro de decisiones nuevas (se llena durante la etapa)

| Fecha | Fase | Decisión | Quién |
|---|---|---|---|
| 2026-10-29 | Plan | Plan maestro aprobado (decisiones D1–D11). | Juan David |
| 2026-10-29 | 0B, 0C | Se agregan limpieza del repo (0B) y línea base de seguridad (0C) antes de la Fase 1A, y seguridad continua por fase (D12–D14). | Juan David (pendiente de confirmar) |

---

## 17. Cambios al plan

| Fecha | Cambio | Motivo | Aprobado por |
|---|---|---|---|
| | | | |

---

## 18. Tablero de estado

| Fase | Estado | Cierre confirmado por Juan David |
|---|---|---|
| 0A · Cierre del piloto | ✔ hecha (30-oct) | ☐ pendiente de tu «sí» |
| 0B · Limpieza y orden del repo | ✔ hecha (2-nov; ver `docs/0B_inventario.md`) | ☐ pendiente de tu «sí» |
| 0C · Línea base de seguridad | ✔ hecha (ver `docs/0C_cierre.md`) | ☐ pendiente de tu «sí» |
| 1A · Puerta rápida | ◐ en curso: base de diseño hecha (3-nov); PR #26 autoimpresión abierto, falta prueba física Brother; faltan buscador único, cola compartida y formulario de persona | ☐ |
| 1B · Impresión con permisos | ☐ | ☐ |
| 2 · Diseño y calendario | ☐ | ☐ |
| 3 · CRUD completo (+ L7 en diciembre) | ☐ | ☐ |
| 4 · Equipo del evento | ☐ | ☐ |
| 5 · Crear y configurar eventos | ☐ | ☐ |
| 6 · Operación sin red | ☐ | ☐ |
| 7 · Cliente y marca | ☐ | ☐ |
| 8 · Vanguardia | ☐ | ☐ |
| 9 · Plataforma y legal | ☐ (intercalada) | ☐ |
| 10 · CRM integrado | ☐ (evaluación en paralelo) | ☐ |

---

## Anexo A · Mapa de los 41 puntos pendientes de Juan David

| Puntos | Tema | Fase |
|---|---|---|
| 1–12 | Ficha, estados, historial, calendario, correos, inventario | 5 (calendario visual en 2) |
| 13–16 | Impresión USB y compartida, iPad | Hechos en producción; verificar en Fase 0 |
| 17–21 | Cédula, autorregistro, compromiso, base de digitadores y clientes | 4 |
| 22 | Informe del cliente con encuesta | 7 |
| 23 | Registro touch | 7 |
| 24, 26 | Servidor local, B8 | 6 |
| 25 | Modo sin conexión encendido | Hecho; verificar en Fase 0 |
| 27–30 | Recarga local-first, lista local, filas por página, Acreditar con Deshacer | Probablemente integrados; verificar en Fase 0 |
| 31 | Logo por defecto | 7 |
| 32 | URL limpia | 7 |
| 33–38 | Respaldos y llave | 9 |
| 39–40 | Política v1.1 y proveedores | 9 |
| 41 | Runbook y guía | Hecho |

## Anexo B · Requisitos nuevos de esta etapa y dónde quedaron

Buscador único (1A) · cola compartida de recién registrados (1A) · formulario de persona con motor de formularios (1A) · reimpresión configurable con permisos por correo (1B) · tema por dispositivo (2) · rediseño del calendario (2) · CRUD completo (3) · carga masiva de temporales con Excel (4) · gestión de bloqueos por el coordinador (4) · compromiso digital con firma y vigencia de 30 días (4) · liberación del evento al cliente por bandera de la comercial y encuesta (7) · CRM integrado con importación desde SugarCRM (10).

| Fecha | Cambio | Motivo | Aprobado por |
|---|---|---|---|
| 2026-11-04 | Pista «Formularios web» entregada a producción (3 y 4-nov): mensaje de cupo lleno editable por cupo, cupo en 0 = «cerrado temporalmente», sesión por inactividad, ahorro de Neon. Estándares visuales unificados en `docs/ux/ESTANDARES_VISUALES.md`. | Cierre de la pista y orden para la Fase 1A/2 | Juan David |
