# Cierre de la Fase 4 — Equipo del evento (8-nov-2026)

Rama `f4/integracion` (integra las cinco ramas de la fase y los ajustes de las pruebas en staging). Aprobada por Juan David el 8-nov-2026 después de probarla en staging. **Producción no tiene nada de esto**: pasa a producción solo con su autorización del commit exacto (ver §6).

Detalle por tema: [`FASE_4_COMPROMISO.md`](FASE_4_COMPROMISO.md), [`FASE_4_CREDENCIALES.md`](FASE_4_CREDENCIALES.md), [`FASE_4_AUTORIZAR_TODOS.md`](FASE_4_AUTORIZAR_TODOS.md), [`FASE_4_CLAVE_PRIMERA_VEZ.md`](FASE_4_CLAVE_PRIMERA_VEZ.md), [`FASE_4_DESCARGAS_BASES.md`](FASE_4_DESCARGAS_BASES.md). Seguridad: [`FASE_4_SEGURIDAD.md`](FASE_4_SEGURIDAD.md).

## 1. Qué quedó construido

| Tema | Qué hace |
|---|---|
| Usuarios temporales (digitadores) | Entran con su cédula (contraseña inicial = cédula). El coordinador autoriza el ingreso, uno por uno o con «Autorizar a todos los pendientes». Cambio de contraseña obligatorio para todos salvo los digitadores. |
| Compromiso digital | Un formulario por evento (motor de formularios web, tipo `pledge`). Camino A: enlace público que crea la cuenta y la asigna. Caminos B/C: la cuenta creada a mano o por Excel firma al ingresar, antes de la fila de espera. Activo por defecto en cada evento nuevo. Sin compromiso firmado no se autoriza el ingreso. Evidencia: huella SHA-256, firma, documento HTML; lo sensible va cifrado y se purga a los 30 días. |
| Alertas del compromiso | La cuenta se ve en amarillo con ícono y dice qué respondió: «Sí» a condición médica, medicamento o apoyo; «No» a condiciones claras o a confirmar asistencia. Solo se guarda **cuáles** preguntas fueron «Sí» (`health_flags`, 0104), nunca el detalle; se borra con la purga. |
| Eliminar cuentas | En «Usuarios temporales» el digitador se **elimina** (no se archiva), también con compromiso firmado (la evidencia queda sin la cuenta, 0102). En Configuración → Staff, el administrador elimina cualquier cuenta que administra salvo un Super Admin y salvo coordinadores/comerciales de un evento. Para quitar acceso sin borrar: «Desactivar». |
| Roles múltiples | Una cuenta coordinador o comercial puede sumar roles (coordinador, comercial, admin; admin solo lo da el Super Admin). Permisos = unión (`auth.effective_roles`). Lista preparada para «bodega» y «contabilidad» cuando existan (`auth.EXTRA_ROLE_CHOICES`). Migración 0103. |
| Editar cuenta | Usuario, nombre, correo y celular en un solo cuadro (`PATCH /api/staff/{id}/profile`). Cambiar el usuario cierra la sesión de esa persona. Solo cuentas de rango inferior; la propia sin cambiar el usuario. |
| Correo de credenciales | Sale por la cola, sin contraseña; mensaje de respaldo impreso. Sin WhatsApp ni SMS. |
| Descargas de bases | Digitadores: admin, coordinador, comercial. Clientes: solo admin y comercial. |
| Presentación del formulario | Ficha del evento, secciones, listas con checks, avisos. El texto legal no cambió. |
| Corrección de «Ya estás inscrito» | Una firma anterior que ya no respalda una firma vigente (cuenta eliminada, reemplazada o re-firma permitida) libera su cédula (`pledge.release_stale`); la evidencia no se toca. |
| Responsive y botones | Revisión de ≈40 pantallas a 320–1500 px; acciones en rejilla de botones iguales; «Copiar» con respaldo (`window.copyText`). |

Migraciones: `0100_event_staff_mail`, `0101_event_staff_pledge`, `0102_pledge_staff_nullable`, `0103_staff_extra_roles`, `0104_pledge_health_flags` (todas aditivas; una sola cabeza).

## 2. Cómo se probó
- Staging (`goldenweb-staging`), despliegues 47 a 61, con Juan David: Camino A y B/C de punta a punta, autorizar a todos, borrado por cuenta y en bloque, roles múltiples, editar cuenta, copiar enlace, alertas, correo, diseño nuevo.
- Responsive medido en un navegador real (desbordes y anchos).
- Pruebas automáticas nuevas: `tests/test_pledge.py`, `tests/test_staff_multirol_perfil.py` y ajustes en `tests/test_staff_archive.py`, `tests/test_crud_gaps.py`, `tests/test_seguridad_cierre_archivos.py`, `tests/test_base_archivada_guard.py`. **Pendiente: la suite completa con base de datos sobre el SHA final** (la corre Juan David en Cloud Shell, ~58 min; ver `scripts/pruebas_cloudshell.sh`).
- Ronda de ataque de seguridad con cinco revisores independientes (§4).

## 3. Decisiones que quedan firmes
- La contraseña inicial del temporal es su cédula; **no se reabre**.
- El coordinador autoriza; la comercial pura nunca administra digitadores.
- Eliminar de verdad cuando se trata de digitadores y cuentas de Staff; «archivar» queda para lo que ya estaba archivado y para cuentas con registros que no se pueden soltar.
- Sesiones: 10 min de inactividad (tope de 12 h para admin).
- `ENFORCE_STAFF_TENANT` sigue apagado; CSP estricto sigue diferido.

## 4. Seguridad
Ver [`FASE_4_SEGURIDAD.md`](FASE_4_SEGURIDAD.md): qué se atacó, qué se encontró y qué se corrigió.

## 5. Pendientes que NO bloquean el cierre
| Pendiente | Quién |
|---|---|
| Texto de autorización de datos sensibles del compromiso (hoy borrador `PENDIENTE_AUDITORA`) y, junto a él: guardar solo **cuáles** preguntas de salud fueron «Sí» (`health_flags`) y cuánto se conserva la evidencia tras eliminar una cuenta | Auditora |
| Autorregistro con consentimiento facial (espera el texto literal de la auditora) | Auditora |
| La firma dibujada no tiene alternativa por teclado | Diseño futuro |
| `deploy.sh` debe usar `PROJECT_ID` en vez del proyecto por defecto de gcloud (causó tres despliegues fallidos) | Siguiente sesión de despliegue |
| Revisar CORS y responsive como paso del despliegue | Siguiente sesión de despliegue |
| Baja severidad restante en `FASE_3_SEGURIDAD.md`, CSP estricto, reemplazo de SheetJS, fijar versiones de dependencias | Fase de seguridad |
| Cerrar/borrar la VM antigua `golden-biometrics-prod` con instantánea final (por confirmar con Juan David qué incluye «lo del GCP») | Juan David |

## 6. Paso a producción (no hecho)
Solo con autorización explícita de Juan David para el commit exacto: copia de la rama de Neon antes, ningún evento «en proceso», sin `FORCE`, migraciones `0100` a `0104` y despliegue con `manual_deploy.sh production`. Staging se queda encendido.

## 7. Siguiente: Fase 5 — Crear y configurar eventos
Ver [`docs/29_PLAN_MAESTRO_ETAPA_2026-10-29.md`](29_PLAN_MAESTRO_ETAPA_2026-10-29.md) §10 y [`CIERRE_FASE_2.md`](CIERRE_FASE_2.md) (lo que la Fase 2 ya adelantó).
