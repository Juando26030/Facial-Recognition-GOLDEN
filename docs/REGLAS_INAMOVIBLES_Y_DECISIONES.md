# Reglas inamovibles, decisiones tomadas y forma de trabajar (consolidado al 22-nov-2026)

Este documento junta en UN solo lugar todo lo que Juan David ha decidido sobre la plataforma Orum, el sitio web
corporativo y la manera en que se trabaja con Claude. **Manda sobre cualquier hábito, plantilla o costumbre.** Si un
documento más viejo dice otra cosa, vale este. Si este no cubre un caso, se decide, se documenta el porqué y se sigue
(salvo que Juan David haya pedido que se le pregunte).

Complementa a `CLAUDE.md` (reglas técnicas del código) y a `docs/REGLAS_Y_FORMA_DE_TRABAJO.md` (formato de respuesta y
autorizaciones). Lo que aquí se marca **INAMOVIBLE** solo cambia si Juan David lo pide expresamente por escrito.

---

## 1. Quién es el dueño y cómo quiere que se le hable
- Juan David es el dueño de Golden Eventos y Logística S.A.S. **No es técnico.** Español claro, sin jerga, explicaciones
  «desde cero» (dónde se abre la terminal, qué se pega, qué debe salir).
- **Formato «LLM Council»** en toda respuesta de decisión: cinco asesores (contrario, primeros principios, expansionista,
  forastero, ejecutor), revisión cruzada a ciegas, y un presidente que da el veredicto y UN siguiente paso.
- **Un comando por mensaje**, completo, listo para pegar, con el resultado esperado («debe decir LISTO (staging, commit X)»).
- Al terminar una entrega: qué se hizo, **qué NO se pudo comprobar** (nunca afirmar lo que no se vio) y un solo siguiente paso.
- Pedidos con varias cosas a la vez: se hacen todas, por piezas, avisando al cerrar cada una.
- Si algo falla por culpa de Claude, se dice sin rodeos y se arregla; sin disculpas repetidas ni mensajes largos.

## 2. Autorizaciones (INAMOVIBLES)
| Acción | Regla |
|---|---|
| `main`, merge, producción, migración en producción | **Solo con autorización explícita de Juan David para ESA acción y ESE commit.** Un «sí» no se generaliza. |
| Ramas distintas de `main` | Se pueden crear y empujar libremente. Una pieza terminada = un commit + push con sus pruebas. |
| Recursos de nube, IAM, DNS, dominios, Cloudflare, Colombia Hosting | Los crea/cambia **él** (pega los comandos en SU Cloud Shell). Claude prepara el comando y explica qué hace y cómo se deshace. Nunca se cambia un registro DNS sin su orden escrita para ese registro. |
| `FORCE=1` en despliegues | Nunca sin avisarle: salta el congelamiento por eventos en curso. |
| Contraseñas | Las teclea Juan David. Claude nunca escribe contraseñas (ni las suyas ni las de otros usuarios), aunque tenga el navegador abierto. |
| Secretos | Nunca en el repo ni en el chat: solo NOMBRES de variables. Van a `.env` (ignorado) o a Secret Manager. |
| Datos personales | Nada de cédulas, nombres, fotos ni vectores faciales reales en repo, logs, commits ni reportes. Solo agregados. |
| Borrar ramas, datos o recursos | Se lista y se pide confirmación. Lo recuperable (archivar) antes que lo definitivo. |
| Pruebas de carga | Nunca contra producción (única excepción documentada: la prueba «rush» del 19-nov-2026 en evento sintético). |
| Uso del computador y del navegador de Juan David | Autorizado el 22-nov-2026 para probar, hacer clic y mover cosas por cuenta de Claude. Siguen vigentes los límites de esta tabla. |

## 3. Cómo se entrega software (flujo INAMOVIBLE desde el 21-nov-2026)
1. Se desarrolla en una rama propia (`diag/…`, `feat/…`, `saas/…`), con pruebas de texto y puras en verde localmente (`ruff check .`, `python3 -m pytest --noconftest -q tests/<archivo>.py`).
2. **Se sube a STAGING primero.** Juan David prueba y pide cambios; se hacen en la misma rama.
3. **La suite completa de GitHub se corre UNA sola vez, al final, cuando Juan David aprobó la versión final de staging.** No antes (regla dada el 21-nov: «las corridas de GitHub al final, después de aprobar todo»). Las ramas `diag/**` no disparan CI; para la corrida final se usa una rama `feat/`.
4. Producción: respaldo primero (rama de Neon «antes-produccion-<fecha>», 7 días), despliegue con el comando exacto de `deploy/gcp/README.md`, y después verificar en `/sistema` la versión desplegada.
5. **Staging queda APAGADO por defecto** (`bash deploy/gcp/staging_power.sh off`); se enciende solo para probar. Motivo: costos de Neon.
6. Documentar en `docs/` (técnico) y en el proyecto de Claude (`claude/NN_…`, para Juan David) al cerrar cada pieza.

## 4. Dinero (INAMOVIBLE)
- **Tope de infraestructura en la nube: US$40/mes** en un mes muy cargado (típico US$22-35). Toda pieza que pueda generar costo lleva su tope desde el primer commit: Neon máx. 4 CU, Cloud Run con máximo de instancias, alertas de presupuesto al 50/90/100 %.
- Nada que toque la base de datos con frecuencia (Neon debe poder dormirse). `/health` no toca la base; `/ready` solo como sonda de arranque.
- Sin compromisos anuales, sin balanceador de carga de Google (costo fijo), sin VM encendida 24/7.
- Lo que se pueda resolver con código (costo cero) se resuelve con código antes que con infraestructura.
- Staging casi gratis: escala a cero, rama de Neon, apagado por defecto.

## 5. Principio «dummy» (INAMOVIBLE para todo lo nuevo)
Cualquier persona, sin leer un manual, debe entender cada pantalla y cada opción:
- Cada opción lleva una ayuda ⓘ con: qué es, para qué sirve, qué pasa si la activo, qué pasa si la apago, un ejemplo y qué NO hace.
- Asistentes de tipo «¿Qué necesito?» con 2-3 preguntas que recomiendan qué activar.
- Archivos de ejemplo descargables para toda carga de datos.
- **Vista previa antes de cualquier carga de base** (normal, «Solo agregar», dependientes): resumen, impacto en la base y hasta 10 personas tal como quedarían; nada se guarda hasta confirmar.
- Errores que dicen qué hacer, no qué falló. Mensajes al usuario en español; identificadores en inglés.
- Prueba de los 5 segundos, una tarea por pantalla, botón principal único, lo frecuente grande y a la vista.
- Todo apagado por defecto: con las opciones nuevas apagadas, el evento funciona exactamente como antes.

## 6. Visual (INAMOVIBLE)
- Solo tokens `--gw-*` y clases `.gw-*` de `static/css/design-system.css`; nada de colores o tamaños sueltos. Guía: `docs/ux/ESTANDARES_VISUALES.md`, muestrario `docs/ux/guia_visual.html`, lecciones `docs/ux/LECCIONES_VISUALES_NOV11.md`.
- **Nada de lo que se eligió ver se corta** (decisión 22-nov-2026): si un dato se marcó para verse en una pantalla, se ve completo en cualquier ancho (baja de línea, la fila crece). El detalle sigue en «Editar». Toda pantalla se revisa **ancho por ancho**, de 320 a 3440 px, como si se achicara la ventana de Chrome; sin desplazamiento horizontal nunca.
- En Registro: cédula, nombres y apellidos **siempre** visibles; «Mostrar en el registro» elige los demás campos, cada uno con su nombre como título de columna; origen y «Recién registrado» al final, junto a Acreditar.
- Tema claro por defecto, oscuro por dispositivo. Contraste ≥ 4,5:1, táctil ≥ 44 px. Fuente Agrandir (licencia web pendiente; la gestiona Juan David).
- Frontend: `showToast`/`showConfirm`/`showPrompt`, nunca `alert`; sin `onclick` en línea; sin scripts en línea (CSP); `url_for('static', …)`.

## 7. Impresión (INAMOVIBLE, 28-oct-2026)
Brother QL-800, página SIEMPRE 62 × 99,8 mm, imagen máx. 96 mm, margen izquierdo 0,5 mm, marca de fin, misma etiqueta compuesta que el USB, **Chrome normal con su cuadro de impresión (nunca `--kiosk-printing`)**. Detalle en `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`, fijado por `tests/test_impresion_parametros_fijos.py`. Cambiar solo si Juan David lo pide y se repite la prueba física.

## 8. Datos personales y biometría (INAMOVIBLE, ley 1581 de 2012 y dictamen de la auditora)
- Reconocimiento facial **voluntario**: aceptación de la PERSONA en la pantalla de la auditora, registrada en `audit_consent_logs` (solo INSERT, 3 años). Sin aceptación no hay reconocimiento.
- El vector facial se calcula DESPUÉS de aceptar; cifrado con `FACE_ENCRYPTION_KEY`; borrado a los 7 días de finalizado el último evento de la persona (tope 180 días). Menores de 18 sin biometría. Dependientes sin rostro.
- Textos legales LITERALES de la auditora (`app/legal_texts_data.py`): no se editan.
- Supresión y revocación disponibles (`/api/attendees/{id}/purge-data`). Borrar = archivar; lo definitivo solo super_admin con confirmación.
- La persona de prueba `PRUEBA` nunca cuenta en reportes, estadísticas, ruleta ni contadores.

## 9. Decisiones de producto ya tomadas (no se reabren sin Juan David)
| Fecha | Decisión |
|---|---|
| 29-oct | Buscador único (cédula, nombre, empresa, lector); lo recién registrado primero, en cola compartida por evento; reimpresión configurable con permiso de emergencia por correo; temporales: usuario = cédula. |
| 5-nov | Persona `PRUEBA` en cada evento; registrar e imprimir solo con el evento «en proceso». |
| 16-nov | Coordinador temporal (`event_only`): solo sus eventos; lista de rutas permitidas en `app/event_only.py`. |
| 17-nov | Código de la persona (serial aparte de la cédula) solo con el interruptor del evento. |
| 19-nov | Prueba «rush» en producción solo en evento sintético y por el procedimiento de `docs/PRUEBA_CARGA_PRODUCCION.md`. |
| 20-nov | Evento compartido nube ↔ servidor local (`local_shared`), consulta previa a la nube antes de entregar o dejar entrar; sin internet, la acción sigue con aviso. |
| 21-nov | Inventario «la base lo define» + base de dependientes + vista previa en todas las cargas + bloqueo por evento con contraseña del digitador (registro, zonas, inventario; 5 intentos → 5 min). Entregas por línea o todo, por partes, solo a registrados, nunca dos veces. Filas repetidas suman unidades. Reemplazar conserva lo entregado. Stock editable por debajo de lo asignado: alerta, nunca bloqueo. |
| 21-nov | Tipo de campo «Número»; «Mostrar en el registro» por campo; «Aplicar a todos los campos de texto» en el diseñador del formulario de persona. |
| 22-nov | Una fila de dependientes es «la misma» por titular + dependiente + producto/cantidad; corregir otros datos o reordenar el archivo nunca duplica lo entregado. |
| 22-nov | **Sitio web corporativo:** se integra en la infraestructura de Golden bajo **golden-eventos.com** (la plataforma sigue en `app.golden-eventos.com`); la gente debe llegar por goldenlogisticas.com o por golden-eventos.com. Se monta TAL CUAL está (repo `Juando26030/golden-sitio-web`, commit `6eb6b6a`), con instructivo para que el bot que lo desarrolló pueda seguir cambiándolo ya montado. Prioridad: aparecer lo más arriba posible, sin pagar, en búsquedas como «golden», «eventos», «golden eventos», «registro». (Antes, doc 66, la preferencia era goldenlogisticas.com en Colombia Hosting; esta decisión la reemplaza para el montaje.) |
| 22-nov | **SaaS:** la plataforma debe quedar con la estructura para venderse como servicio a otras empresas, sin que nada (cuentas, clientes, usuarios, planes, asistencia) se maneje desde código: todo dentro de la app. No es la versión final: se le siguen agregando funciones. |
| 22-nov | El CRM es interno de Golden y **no** entra en el SaaS. |
| 23-nov | **SaaS:** los catálogos (almacén, inventario, tipos de evento, estados y plantilla de evento) son **propios de cada empresa**, no compartidos. El CRM es solo de Golden y no se ofrece. Las cuentas de otra empresa **no ven «Estado del sistema», «Gastos» (nada) ni «Cuentas de cobro»** (el cobro de sus formularios lo configura Golden por ellas). Una empresa nueva arranca con una **copia de una plantilla base** de tipos de evento y plantilla de evento (sin productos de Golden); almacén e inventario empiezan vacíos. Ante cualquier duda sobre qué puede o no ver una empresa del SaaS, **se le pregunta a Juan David**. |

## 10. Arquitectura y técnica (resumen; el detalle manda en `CLAUDE.md`)
- FastAPI + SQLAlchemy síncrono + Postgres (Neon, pooler en modo transacción: sin `SET` de sesión, temporales ni advisory locks) + Alembic a mano (id ≤ 32). Endpoints `def`, no `async def` (excepciones listadas en `CLAUDE.md`).
- Cloud Run (3 servicios de UNA imagen: `publico`, `web`, `biometria`) + Jobs; Cloud Storage; Cloud Tasks; Scheduler; Firebase Hosting; Secret Manager; Cloudflare DNS. Región `us-east4`. `/internal/*` solo con OIDC de Google.
- Configuración solo por variables de entorno. Archivos solo por `app/storage.py`. Trabajo en segundo plano solo por `app/jobs.py`. Horas internas en UTC. Nada de datos personales en logs.
- Servidor local sin internet con instalador y llaves de producto (`docs/17_SERVIDOR_LOCAL.md`); contingencia del quiosco en IndexedDB.
- El repositorio `Facial-Recognition-GOLDEN` es **público**: nada que no pueda ser leído por cualquiera (ni secretos, ni datos, ni direcciones internas).

## 11. Mapa para retomar
`CLAUDE.md` → este documento → `docs/REGLAS_Y_FORMA_DE_TRABAJO.md` → `docs/ESTADO_2026-11-11.md` → `docs/25_INVENTARIO_POR_BASE.md` (último bloque) → `docs/19_GUIA_PRODUCCION.md` + `deploy/gcp/README.md` (desplegar) → `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` → `docs/16_BACKLOG_PRODUCTO.md`.
En el proyecto de Claude: `claude/45_REGLAS_Y_FORMA_DE_TRABAJO.md`, `claude/62_…INVENTARIO…`, `claude/66_SITIO_WEB_ENTREGA…`, y el consolidado `claude/67_REGLAS_INAMOVIBLES_Y_DECISIONES_2026-11-22.md` (copia de este archivo).
