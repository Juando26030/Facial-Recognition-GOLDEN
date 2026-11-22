# 10 · SaaS: primera pieza de la capa «empresa» (22-nov-2026)

Rol: desarrollador. Encargo: construir la primera pieza de «nada se maneja desde código: cuentas, empresas, planes y asistencia, todo dentro de la app» (decisión de Juan David, 22-nov).
Rama `saas/revision-integral`, sin commit ni push. Guía de uso: [`docs/27_SAAS_EMPRESAS.md`](../27_SAAS_EMPRESAS.md).

## 1. Resumen en 5 líneas
1. **Quedó el armazón**: existe la «empresa» (`organizations`, Golden = 1), sus planes y límites, una pantalla «Empresas (SaaS)» para el Super Admin y un primer arranque `/instalar` sin scripts. Todo es aditivo: para Golden nada cambia.
2. **Lo más grave (y por eso quedó cerrado con candado):** la plataforma todavía NO aísla por empresa. Una cuenta de otra empresa vería los eventos de Golden. La app **se niega** a crear el administrador de una empresa ajena mientras `ENFORCE_STAFF_TENANT` esté en 0.
3. **Lo más valioso:** dar de alta una empresa, elegir su plan, hacerle una excepción a un límite o suspenderla ya no necesita a un programador; y el tope de «eventos por mes» ya frena de verdad al crear un evento.
4. **Lo que no se pudo probar:** las pruebas con base de datos están escritas pero **no se corrieron** (en este entorno no están instalados FastAPI ni SQLAlchemy). Sí corrieron las 22 pruebas puras/de texto, la cadena de migraciones y `ruff`.
5. **Queda una decisión de seguridad abierta:** la prueba que lista las rutas sin sesión falla a propósito con `/instalar` hasta que alguien la autorice en esa lista.

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | **Crítica (al abrir el SaaS)** | No hay aislamiento por empresa: `org_id` existe en dos tablas pero ninguna consulta filtra por él. El único aislamiento es por cliente (`ENFORCE_STAFF_TENANT`), apagado. | `app/auth.py`, `app/tenant_scope.py` | Dar una cuenta a otra empresa hoy expondría datos personales de los clientes de Golden (ley 1581). | **Corregido en lo que toca a esta pieza**: `POST /api/platform/orgs/{id}/admin` responde 409 para empresas distintas de Golden con el interruptor en 0; con el interruptor en 1 la cuenta nace atada al cliente propio de su empresa. El filtro real por `org_id` queda **Pendiente** (pieza 3). |
| 2 | Alta | `tests/test_seguridad_2026-11-22.py::test_rutas_sin_autenticacion_son_solo_las_publicas_conocidas` **falla** con `/instalar` (GET y POST): son rutas nuevas sin sesión que no están en su lista. | `tests/test_seguridad_2026-11-22.py` (`PUBLIC_ROUTES`) | Es el trinquete de seguridad haciendo su trabajo. Agregar una ruta pública es una decisión, no un trámite. | **Pendiente (decisión de Juan David)**. Intenté agregar las dos rutas a la lista y el sistema de permisos lo negó; no lo forcé. Opciones: (a) autorizar las dos líneas; (b) quitar `/instalar` y seguir con el script. |
| 3 | Alta | `/instalar` es una puerta abierta en una instalación nueva: quien llegue primero se queda con el Super Admin. | `app/routers/platform.py` | En un despliegue nuevo expuesto a internet alguien podría adelantarse. | **Corregido**: solo abre sin ninguna cuenta activa; 404 después y siempre en servidor local; bloqueo de tabla para que no haya dos «primeros»; código opcional `INSTALL_TOKEN`. Producción y staging ya tienen cuentas: ahí es 404. |
| 4 | Media | Suspender una empresa impide crear eventos y cuentas, pero **no cierra el ingreso** de su personal. | `app/routers/auth.py` (no tocado) | «Suspender» sugiere más de lo que hace. | **Propuesto**: cerrar el ingreso en `complete_login` (pieza 3, 2-3 h). La pantalla y `docs/27` lo dicen tal cual. |
| 5 | Media | Solo se aplica UN límite (eventos por mes). Usuarios, asistentes por evento, facial, servidor local, pagos y marca se configuran pero no frenan (salvo «usuarios» al crear el administrador). | `app/orgs.py` | Un plan «Básico» hoy podría cargar 10.000 asistentes. | **Pendiente** (16-24 h): `orgs.check_limit` ya está listo para llamarse en cada punto. |
| 6 | Media | Por ahora una empresa ajena = un solo cliente (`tenant`). | `app/orgs.py` (`home_tenant`) | Una empresa de eventos tiene varios clientes. | **Pendiente**: sale con el filtro por `org_id` (pieza 3). |
| 7 | Media | `org_id` no tiene llave foránea ni `NOT NULL`. | `alembic/versions/0162_organizations.py` | Podría quedar un `org_id` que no existe. | **Decisión documentada**: la base de pruebas vacía todas las tablas en cada prueba (incluida `organizations`), y una llave foránea rompería toda la suite. El código trata «empresa inexistente» como suspendida. La llave llega con la migración que quite el valor por defecto. |
| 8 | Baja | La tabla difiere del boceto de A.3 (aquí: `legal_name`, `contact_*`, `plan`, `entitlements_json`, `status`, `notes`; allá: política, remitente, color, logo) y los límites van en una columna JSON, no en `org_entitlements`. | migración 0162 | Evitar sorpresas al seguir el plan. | **Hecho según el encargo**; la equivalencia está en `docs/27` §5. |
| 9 | Baja | Los valores de los planes son una propuesta (reporte 07), no precios aprobados. | `app/orgs.py` (`PLANS`) | No prometerlos a un cliente. | **Propuesto**: Juan David los confirma; se cambian en un solo sitio o por empresa en la pantalla. |
| 10 | Baja | La pantalla global `/plataforma` no está en la lista de páginas negadas del coordinador temporal (`PAGE_DENIED_PREFIXES`). | `app/event_only.py` (no tocado) | Sin efecto: la página exige `super_admin` y la API está en lista de permitidos (cerrada). | **Propuesto**: agregarla por coherencia (5 min). |

## 3. Qué se cambió en el código

Nuevos:
- `alembic/versions/0162_organizations.py`: tabla `organizations` con la fila 1 = Golden (`slug='golden'`, plan `interno`); `org_id` (NULL, valor por defecto 1, con índice) en `tenants` y `staff_users`. Aditiva, a mano, sin `SET` de sesión, con `downgrade`.
- `app/orgs.py`: planes (`interno`, `basico`, `pro`, `empresa`), `entitlement`, `check_limit` (mensaje «Tu plan permite N …; contacta a soporte»), `current_org`, `usage`, `create_org`, `create_admin`, `create_org_with_admin`. La lógica pura no importa SQLAlchemy.
- `app/routers/platform.py`: `/api/platform/*` (solo `super_admin`, endpoints `def`): catálogo, listar, crear, editar, suspender, reactivar, primer administrador, uso. Y `/instalar` (GET/POST).
- `templates/plataforma.html`, `static/js/plataforma.js`: pantalla sin scripts en línea, con ayuda ⓘ en cada opción, `showToast`/`showConfirm`, solo clases `.gw-*` (no hizo falta CSS nuevo).
- `templates/instalar.html`, `static/js/instalar.js`: **fuera de la lista literal del encargo**, pero `/instalar` necesita su página; son archivos nuevos y no chocan con nadie.
- `tests/test_saas_organizations_puro.py` (22 casos sin base, en verde) y `tests/test_saas_organizations.py` (21 pruebas con base, sin ejecutar).
- `docs/27_SAAS_EMPRESAS.md`.

Modificados (solo agregando):
- `app/models.py`: clase `Organization`; `Tenant.org_id`; `StaffUser.org_id`.
- `app/main.py`: registro de los dos routers y la página `/plataforma`.
- `app/routers/events.py`: 4 líneas en `create_event` (tope de eventos del mes; Golden no cuesta ninguna consulta extra).
- `templates/_sidebar.html`: entrada «Empresas (SaaS)» solo para `super_admin`, en la nube.
- `deploy/gcp/env/common.yaml`, `.env.example`: `ENFORCE_STAFF_TENANT` y `ENFORCE_STAFF_EVENT_SCOPE` en 0 con el aviso; `INSTALL_TOKEN` comentado (solo el nombre).
- `docs/16_BACKLOG_PRODUCTO.md` (sección «SaaS» al final), `CLAUDE.md` (una línea en el mapa).

No se tocó `app/auth.py`, `scripts/create_staff_user.py` (sigue igual; ya no hace falta para arrancar) ni la prueba de seguridad.

Mecanismo de contraseña temporal: se reutilizó el existente (`must_change_password`, `docs/FASE_4_CLAVE_PRIMERA_VEZ.md`). La contraseña se genera en el servidor, se muestra una sola vez y no se guarda en claro.

## 4. Qué queda pendiente y por qué (orden recomendado)

| Orden | Qué | Horas |
|---|---|---|
| 1 | Decidir el hallazgo 2 (autorizar `/instalar` en la lista de rutas públicas, o retirarla) | 0,2 |
| 2 | Correr `tests/test_saas_organizations.py` y la suite completa con base; corregir lo que salga | 2-4 |
| 3 | Pieza 3 de A.3: filtro por `org_id` en `app/auth.py`, cierre del ingreso de empresas suspendidas, prueba de dos empresas; encender `ENFORCE_STAFF_TENANT=1` en staging | 20-30 |
| 4 | `org_id` en `events` y catálogos globales; `SET LOCAL app.org_id`; RLS tabla por tabla | 40-55 |
| 5 | Aplicar los demás límites y ocultar lo interno de Golden (CRM, legalizaciones, almacén, gastos) | 16-24 |
| 6 | Identidad, marca, correo y textos legales por empresa (más contrato de encargo con la auditora) | 24-32 + legal |
| 7 | Estado de cuenta y cobro, exportar/borrar todo, «Pedir ayuda», «entrar como», rol `platform_admin` | 60-90 |
| 8 | Llaves/nodos locales, cola y archivos por empresa | 36-48 |

## 5. Qué NO se pudo comprobar
- **Las 21 pruebas con base no se ejecutaron**: aquí no hay FastAPI, SQLAlchemy, Alembic ni bcrypt instalados y no hay red para instalarlos. Tampoco la suite completa con base. Es probable que alguna necesite un ajuste al correrla.
- La migración 0162 no se corrió con Alembic. Sí se comprobó a mano, en un PostgreSQL 16 local desechable, el SQL delicado: insertar la fila 1 con id explícito, ajustar la secuencia (la siguiente empresa recibe el 2), el valor por defecto 1 en filas existentes y el bloqueo de tabla.
- Las dos plantillas se renderizaron con Jinja2 suelto (sin la app): sin errores, sin ids repetidos y con el enlace del menú solo para Super Admin en la nube. **No se vieron en un navegador**: ni anchos de 320 a 3440 px, ni tema oscuro, ni los cuadros de ayuda dentro de las ventanas.
- `/instalar` detrás de Firebase Hosting (reparto de rutas entre servicios) no se probó. Nada se desplegó ni se probó en staging.
- Que `ENFORCE_STAFF_TENANT=1` aísle de verdad a una cuenta atada a un cliente lo afirman el reporte 03 y pruebas existentes; no lo verifiqué yo.

## 6. Consejo en corto y veredicto
- **Contrario:** «Una pantalla de empresas sin aislamiento es una invitación a usarla antes de tiempo; el candado del 409 es lo único que la hace aceptable.»
- **Primeros principios:** «Un SaaS es aislamiento + cobro; esta pieza no da ninguno de los dos, da el lugar donde vivirán.»
- **Expansionista:** «Con planes editables por empresa ya se puede ofrecer una prueba a un prospecto en cuanto la pieza 3 esté lista.»
- **Forastero:** «Entendí la pantalla sin manual, pero "Suspender" debería impedir entrar; hoy no lo hace.»
- **Ejecutor:** «Correr las pruebas con base, decidir lo de `/instalar` y subir a staging; después, pieza 3.»

**Veredicto:** la pieza cumple su papel de estructura y no cambia nada para Golden, pero no está verificada con base de datos ni lista para un cliente real.
**UN siguiente paso:** correr `python -m pytest -q tests/test_saas_organizations.py "tests/test_seguridad_2026-11-22.py"` en un entorno con las dependencias y decidir si `/instalar` entra en la lista de rutas públicas.
