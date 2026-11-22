# 27 · SaaS: empresas, planes y primer arranque (primera pieza, 22-nov-2026)

Decisión de Juan David (22-nov-2026): **«nada se maneja desde código: cuentas, empresas, planes y asistencia, todo dentro de la app»**.
Esta es la PRIMERA pieza de esa estructura. No es la versión final: deja el armazón para seguir agregando. Migración `0162_organizations`.
Sin desplegar; rama `saas/revision-integral`.

## 1. Qué existe hoy

| Qué | Dónde | Para qué |
|---|---|---|
| Tabla `organizations` (la EMPRESA que usa la plataforma) | `alembic/versions/0162_organizations.py`, `app/models.py` (`Organization`) | Un nivel por encima de «clientes». Golden es la fila 1 (`slug='golden'`, plan `interno`). |
| `tenants.org_id` y `staff_users.org_id` (NULL o 1 = Golden) | misma migración | Saber de qué empresa es cada cliente y cada cuenta del personal. Todo lo que ya existía queda en Golden. |
| Planes y límites | `app/orgs.py` (`PLANS`, `entitlement`, `check_limit`, `usage`) | Valores de fábrica por plan + límites propios por empresa (`entitlements_json`). |
| Pantalla **Empresas (SaaS)** | `/plataforma` (menú lateral, solo Super Admin; `templates/plataforma.html`, `static/js/plataforma.js`) | Crear, editar, suspender y reactivar empresas; crear su primer administrador; ver su consumo. |
| API | `app/routers/platform.py`, prefijo `/api/platform` (solo `super_admin`) | Lo que usa la pantalla. |
| Primer arranque sin scripts | `/instalar` (`templates/instalar.html`, `static/js/instalar.js`) | Crear el primer Super Admin desde el navegador en una instalación nueva. |
| Un límite aplicado de verdad | `app/routers/events.py` (`create_event`) | Tope de **eventos por mes** de la empresa dueña del cliente. Golden nunca se limita. |

### Lo que esta pieza NO hace (importante)
- **No aísla por empresa.** El aislamiento que existe es el de siempre, por cliente (`ENFORCE_STAFF_TENANT`), y hoy está apagado. Por eso la app **se niega** a crear el
  administrador de una empresa distinta de Golden mientras ese interruptor esté en 0 (responde 409 y la pantalla muestra un aviso). Crear la empresa y elegir su plan sí se puede.
- Cuando el interruptor está en 1, el administrador de otra empresa nace **atado al cliente propio de su empresa** (se crea solo, con el nombre de la empresa): ve y opera únicamente ese
  cliente. Es decir, por ahora **una empresa = un cliente**. Que una empresa tenga varios clientes llega con el filtro por `org_id` (pieza 3 del plan).
- Suspender una empresa le impide crear eventos y cuentas nuevas; **todavía no** le cierra el ingreso (eso toca `app/routers/auth.py`, pieza 3).
- Solo se aplica el límite de eventos por mes. Los demás límites ya se pueden configurar y consultar (`orgs.check_limit`), pero aún no frenan nada.
- No hay cobro, marca propia, soporte dentro de la app ni RLS. Ver §5.

## 2. Cómo dar de alta una empresa (paso a paso, para Juan David)

1. Ingresa con tu cuenta de Super Admin. En el menú de la izquierda abre **Empresas (SaaS)**.
2. Pulsa **Nueva empresa**. Escribe el nombre (lo único obligatorio), elige el **plan** y guarda. Cada casilla tiene una ayuda ⓘ que explica qué es, para qué sirve y un ejemplo.
3. La empresa aparece en la lista con su consumo: «Eventos este mes: 0 de 4», «Usuarios activos: 0 de 15», etc.
4. Pulsa **Crear administrador** en esa empresa. Escribe usuario, nombre, correo y teléfono de la persona.
5. La app muestra **una sola vez** una contraseña temporal. Cópiala y entrégasela a la persona por un medio seguro (en persona o por llamada). Nadie escribe ni elige esa contraseña: la genera el servidor.
6. La persona ingresa por `/login` con ese usuario y esa contraseña, y la app la obliga a elegir una propia antes de hacer cualquier otra cosa (mecanismo de «clave de primer ingreso», `docs/FASE_4_CLAVE_PRIMERA_VEZ.md`).
7. Desde ahí ella crea el resto de su equipo en Configuración › Personal, como hoy.

Para cambiar el plan, hacer una excepción a un límite, suspender o reactivar: botón **Editar** / **Suspender** de la empresa. Todo queda en el registro de acciones (`audit_actions`).

### Antes del primer cliente (obligatorio; hoy el paso 4 está bloqueado para empresas que no sean Golden)
1. En **staging**, poner `ENFORCE_STAFF_TENANT=1` (y `ENFORCE_STAFF_EVENT_SCOPE=1` si se quiere que coordinador y comercial vean solo sus eventos). Están escritas en `deploy/gcp/env/common.yaml`
   y `.env.example` con valor `0` y el aviso. El personal de Golden no tiene cliente asignado (`tenant_id` vacío), así que `ENFORCE_STAFF_TENANT=1` no le cambia nada; `ENFORCE_STAFF_EVENT_SCOPE=1`
   sí puede dejar a un coordinador sin ver eventos donde no esté asignado: revisar antes.
2. Crear una empresa de prueba y su administrador; entrar con esa cuenta y comprobar que NO ve eventos, clientes, personal ni imágenes de Golden (plan del reporte `docs/revision_2026-11-22/03_seguridad_nube.md`, hallazgo 1).
3. Prueba de penetración externa (la exige `docs/29`).
4. Solo entonces, lo mismo en producción, con autorización de Juan David para ese despliegue.

## 3. Planes y límites

Valores de fábrica (propuesta del reporte `docs/revision_2026-11-22/07`, §2.3 b). **Son un punto de partida, no precios ni compromisos**: se cambian en `app/orgs.py` (`PLANS`) para todos, o por empresa
desde la pantalla, sin tocar código.

| Límite (clave) | Interno (Golden) | Básico | Pro | Empresa |
|---|---|---|---|---|
| Eventos por mes (`events_per_month`) | sin límite | 1 | 4 | sin límite |
| Asistentes por evento (`attendees_per_event`) | sin límite | 500 | 3.000 | 15.000 |
| Usuarios (`users`) | sin límite | 5 | 15 | sin límite |
| Reconocimiento facial (`facial`) | sí | no | sí | sí |
| Servidor local (`local_server`) | sí | no | sí | sí |
| Formularios con pago (`paid_forms`) | sí | no | sí | sí |
| Marca propia (`own_brand`) | sí | no | sí | sí |

- **Límites propios de una empresa** (`organizations.entitlements_json`): pisan los del plan. En la pantalla, cada límite ofrece «Lo del plan», «Valor propio» o «Sin límite» (y Sí/No para las funciones).
  En la base: clave ausente = lo del plan; clave en `null` = sin límite.
- **Golden (empresa 1) nunca se limita**, diga lo que diga su fila; no cambia de plan ni se suspende.
- Mensaje al llegar al tope: «Tu plan permite 4 eventos por mes; contacta a soporte» (403). Empresa suspendida: «La cuenta de tu empresa está suspendida; contacta a soporte».
- «Eventos por mes» cuenta los eventos **creados** en el mes calendario (UTC) en los clientes de la empresa. «Usuarios» cuenta cuentas activas sin digitadores ni clientes temporales.
  La persona de prueba (`PRUEBA`) no cuenta.

Para aplicar un límite en otro punto (ejemplo, al crear una cuenta):
```python
from app import orgs
ok, message = orgs.check_limit(db, orgs.current_org(staff), "users")
if not ok:
    raise HTTPException(status_code=403, detail=message)
```

## 4. Primer arranque sin scripts (`/instalar`)

- En una instalación nueva (ninguna cuenta activa del personal), abrir `https://<dominio>/instalar`: pide usuario, nombre, correo y la contraseña **que escribe la persona** (mínimo 10 caracteres,
  letras y números, no común, distinta del usuario). Crea el primer Super Admin y lleva a «Ingresar».
- En cuanto existe una cuenta activa, `/instalar` responde **404 para siempre** (GET y POST). En un servidor local nunca existe (sus cuentas llegan de la nube).
- Recomendado en un despliegue nuevo expuesto a internet: definir el secreto `INSTALL_TOKEN` (Secret Manager o `.env`; nunca en el repo). Con él, la pantalla pide además ese código, para que nadie se adelante.
- `scripts/create_staff_user.py` **ya no hace falta** para arrancar; se deja igual por compatibilidad (recuperación por consola si alguna vez se pierde el acceso).
- Producción y staging ya tienen cuentas: ahí `/instalar` responde 404 desde el primer momento.
- **Pendiente de decisión:** la prueba de seguridad `tests/test_seguridad_2026-11-22.py` (`test_rutas_sin_autenticacion_son_solo_las_publicas_conocidas`) lleva la lista de rutas que se abren sin sesión y
  **falla a propósito** con `/instalar` (GET y POST) hasta que alguien las agregue a esa lista de forma consciente. No se agregaron en esta entrega: es una decisión de seguridad de Juan David.

## 5. Qué falta y en qué orden

Orden del Anexo A.3 del reporte `docs/revision_2026-11-22/01_arquitectura_devops.md` (11 piezas), con lo que esta entrega adelantó:

| # | Pieza (A.3) | Estado | Notas |
|---|---|---|---|
| 1 | Migración `organizations` + `org_id` | **Parcial (esta entrega)** | Hecho: tabla y `org_id` en `tenants` y `staff_users`, NULL con valor 1, sin llave foránea. Falta: `org_id` en `events` y en los catálogos globales (estados, tipos, inventario, impresoras, ajustes, llaves locales, plantillas…), llave foránea y `NOT NULL`. La tabla usa `legal_name`, `contact_email`, `contact_phone`, `plan`, `entitlements_json`, `status`, `notes`; los campos de identidad y marca de A.3 (`privacy_email`, `policy_version`, `sender_email`, `brand_color`, `logo_key`…) llegan con la pieza 6. |
| 2 | Modelos; rol `platform_admin` | **Parcial** | Hecho: `Organization`, `Tenant.org_id`, `StaffUser.org_id`. Falta el rol `platform_admin` (hoy la plataforma la opera `super_admin`, que sigue siendo único de Golden). |
| 3 | `app/auth.py`: filtrar SIEMPRE por `org_id`; bloquear el ingreso de una empresa suspendida | Pendiente | Es la pieza que permite varios clientes por empresa y retira los interruptores `ENFORCE_*`. 20-30 h. |
| 4 | `SET LOCAL app.org_id` por transacción | Pendiente | Primero probarlo contra el pooler de Neon en staging. 8-12 h. |
| 5 | Migración RLS, tabla por tabla, con prueba de dos empresas | Pendiente | 24-32 h. |
| 6 | `app/org_settings.py`: identidad, remitente y política por empresa | Pendiente | 24-32 h. Incluye textos legales por empresa (los actuales son de la auditora PARA Golden: una empresa cliente no puede usar facial con ellos). |
| 7 | Planes y cuotas | **Parcial (esta entrega)** | Hecho: `app/orgs.py` con planes, límites propios y `check_limit`; aplicado en «crear evento». Se guardan en `organizations.entitlements_json` (no en una tabla `org_entitlements` aparte: se separa cuando haga falta historial). Falta aplicarlo en: crear cuenta de personal, asistentes por evento (cargas), activar facial, llaves de servidor local, formularios con pago; y ocultar CRM/legalizaciones/almacén/gastos a quien no es Golden. 16-24 h. |
| 8 | `app/routers/platform.py` + pantalla | **Parcial (esta entrega)** | Hecho: empresas, plan, límites, suspender, primer administrador, consumo. Falta: «entrar como» con auditoría, llaves locales por empresa, correo de bienvenida, estado de cuenta y cobro, «Pedir ayuda» (soporte dentro de la app). 40-60 h. |
| 9 | Cuotas en cola y cargas (`jobs`, `bulk_jobs`) | Pendiente | 12-16 h. |
| 10 | Llaves y nodos locales con `org_id` | Pendiente | 12-16 h. |
| 11 | Archivos con prefijo de empresa | Pendiente | 12-16 h. |

Siguiente paso recomendado: **pieza 3** (filtro por `org_id` en `app/auth.py` + cierre del ingreso de empresas suspendidas), con la prueba de dos empresas, y encender `ENFORCE_STAFF_TENANT=1` en staging.

## 6. Pruebas
- Sin base: `python3 -m pytest --noconftest -q tests/test_saas_organizations_puro.py` (planes, límites, mensajes, migración, reglas del frontend, configuración).
- Con base: `python -m pytest -q tests/test_saas_organizations.py` (migración, empresa, administrador, límite de eventos, `/instalar`).
