# Arquitectura — GoldenWeb 2.0

> Documento de arquitectura a nivel de producto/decisión. El detalle vivo de
> implementación (estructura real de archivos, convenciones de código) vive
> en `CLAUDE.md` dentro del repo y lo mantiene la sesión de código.

## 1. Vista de contexto

```
        ┌───────────────┐        ┌────────────────────┐
        │   Comercial /  │        │      Cliente        │
        │  Coordinador   │        │  (empresa contratante)│
        └───────┬───────┘        └──────────┬──────────┘
                │ crea/gestiona eventos       │ ve estadísticas de su evento
                ▼                              ▼
        ┌─────────────────────────────────────────────┐
        │                GoldenWeb 2.0                  │
        │   (FastAPI + PostgreSQL, multi-tenant)         │
        └───────┬───────────────────┬───────────────────┘
                │                    │
                ▼                    ▼
        ┌───────────────┐    ┌───────────────────┐
        │  Digitador /   │    │ Lector de código   │
        │  kiosko facial/│◄───┤ de barras (cédula) │
        │  touch         │    └───────────────────┘
        └───────────────┘
```

## 2. Stack tecnológico (decidido, ya en uso)

| Capa | Tecnología | Nota |
|---|---|---|
| Backend | FastAPI (Python 3.14) + Uvicorn | — |
| ORM / migraciones | SQLAlchemy + Alembic | 7 migraciones aplicadas, reemplazó `create_all()` |
| Base de datos | PostgreSQL | Rol de mínimo privilegio (no superusuario) desde el incidente de seguridad resuelto |
| Biometría | `face_recognition` (dlib) | Tolerancia 0.55, jitters 25 (registro) / 10 (reconocimiento) |
| Frontend | Jinja2 + JS plano | Sin framework — decisión existente, no se propone cambiar por ahora |
| Infra | VM GCP (`golden-biometrics-prod`, Ubuntu, IP fija) + Nginx + Cloudflare + Certbot | — |
| Proceso | systemd (`facial-recognition.service`) | Mantiene viva la app, reinicia ante caídas |
| CI/CD | GitHub Actions con runner **self-hosted** en la misma VM | Se eligió self-hosted porque el proyecto tiene OS Login activado en GCP (no SSH abierto desde afuera) |
| Autenticación | Roles propios: `super_admin`, `admin`, `coordinador`, `digitador`, `cliente` | Antes no existía autenticación |

## 3. Estructura actual (rama `feature/auth-roles-events`, aún sin mergear)

```
app/
  main.py            FastAPI app, SessionMiddleware, dashboard (/) y /kiosk/{event_id}
  database.py        Engine SQLAlchemy — falla explícito si falta DATABASE_URL
  models.py          Tenant, User, AccessLog, StaffUser, Event, EventStaffAuthorization
  auth.py            Hashing, get_current_staff, require_role, get_event_for_staff
  biometrics.py      BiometricEngine
  reports.py         ReportManager (Excel)
  cities_data.py     Dataset de ~20,300 ciudades (GeoNames) para el formulario de evento
  routers/
    api.py             Endpoints biométricos, event-scoped
    auth.py            /login, /logout
    tenants.py         CRUD de clientes
    events.py          CRUD de eventos, ciudades, usuarios temporales/cliente del evento
    staff.py           Cuentas coordinador/admin
alembic/             Migraciones versionadas (0001-0007 hasta ahora)
scripts/create_staff_user.py   Bootstrap del primer Super Admin
templates/           dashboard.html, kiosk_select.html, kiosk.html, login.html, staff.html
static/js/           clockpicker.js, toast.js, app.js
```

Todavía en la raíz del repo (no en `apps/`) — la migración a monorepo
(§5 más abajo) sigue pendiente de ejecutar.

## 4. Decisiones de arquitectura (registro tipo ADR, resumido)

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| ADR-1 | Multi-tenant real con entidades `Tenant` y `Event` | Seguir con tenant hardcodeado | Es requisito explícito del negocio: dar servicio a varios clientes desde la misma instalación |
| ADR-2 | Roles fijos (`super_admin`/`admin`/`coordinador`/`digitador`/`cliente`) en vez de permisos granulares desde el inicio | Sistema de permisos por acción | Roles fijos son suficientes para el volumen de usuarios actual; permisos granulares quedan en backlog (M9-3) cuando haga falta |
| ADR-3 | Ciclo de vida de evento `creado → en_proceso → finalizado`, bloqueado en UI | Dejar el registro siempre abierto | Evita registrar gente en eventos que no han arrancado o ya cerraron — error operativo real del negocio |
| ADR-4 | Migrar a **monorepo** (`apps/<módulo>/`) para los módulos nuevos | Un repo por módulo | El objetivo explícito del rediseño es que meter un módulo nuevo sea fácil; un monorepo comparte auth/tenant/eventos sin duplicar infraestructura ni tener que sincronizar versiones entre repos |
| ADR-5 | Runner self-hosted de GitHub Actions en la VM, no SSH desde GitHub | Acción de deploy por SSH externo | OS Login de GCP no deja abrir SSH público de forma simple; el runner corre local y no necesita exponer el puerto 22 |
| ADR-6 | El encoding facial se guarda como JSON en columna `Text`, no en un tipo vectorial | pgvector u otro motor de búsqueda vectorial | El volumen actual (cientos/miles de personas por evento, no millones) no justifica la complejidad extra; se reconsidera si el volumen crece un orden de magnitud |

## 5. Estructura objetivo (monorepo)

Pendiente de ejecutar (ADR-4). Propuesta, a validar con la sesión de código
antes de moverla:

```
Facial-Recognition-GOLDEN/
├── apps/
│   ├── core/            # tenants, eventos, roles, auth — ya existe, se mueve aquí
│   ├── facial/           # motor biométrico facial — ya existe, se mueve aquí
│   ├── cedula/            # registro por cédula/código de barras (Épico 1)
│   ├── badges/            # diseñador e impresión de escarapelas (Épico 2)
│   ├── forms/              # formularios web propios (Épico 5)
│   ├── reports/             # informes y estadísticas (Épico 4, 6)
│   ├── client-portal/       # portal de cliente (Épico 6)
│   └── staffing/             # personal y facturación interna (Épico 7)
├── CLAUDE.md
├── docs/                       # documentos de este conjunto (visión, backlog, arquitectura, modelo de datos)
└── .github/workflows/
```

Cada `apps/<módulo>` comparte el modelo de `Tenant`/`Event`/roles de `core`,
pero puede tener sus propias tablas y routers — así un módulo nuevo no
obliga a tocar los existentes (criterio de éxito #3 de `01_VISION_Y_ALCANCE.md`).

## 6. Vista de despliegue

```
Internet
   │
   ▼
Cloudflare (proxy + DNS)  ──HTTPS──►  Nginx (VM, Certbot)  ──►  Uvicorn :8000  ──►  PostgreSQL (local)
                                            ▲
                                            │ systemd mantiene vivo
                                            │
                                   GitHub Actions runner (self-hosted, misma VM)
                                            ▲
                                            │ push a main
                                        GitHub (repo)
```

## 7. Riesgos de arquitectura conocidos

- **Un solo desarrollador + un agente de código**: la documentación (este
  conjunto de documentos) hace las veces de "equipo" — hay que mantenerla
  actualizada o se vuelve más un estorbo que una ayuda.
- **Runner self-hosted en la misma VM de producción**: si un despliegue
  rompe el runner, no hay forma de desplegar el fix sin acceso manual a la
  VM — vale la pena un plan B documentado (acceso de emergencia).
- **Sin tests automatizados todavía** (ver `CLAUDE.md` §7): cada módulo nuevo
  que se agregue aumenta el riesgo de romper algo existente sin que el CI lo
  detecte.
- **Offline/sync (M1-10, M9-2)** es la pieza de mayor incertidumbre técnica
  del backlog — se dejó en Fase D a propósito, no se ha diseñado todavía.
