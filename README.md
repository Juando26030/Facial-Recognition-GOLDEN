# Orum

Plataforma de **gestión de identidades y control de acceso para eventos** de Golden Eventos y Logística S.A.S.: inscripción por formulario web
(con pagos por Wompi), carga de bases, acreditación en la puerta por cédula, QR o **reconocimiento facial voluntario**, escarapelas impresas y digitales,
certificados, inventario y control de áreas, ruleta de sorteos, estadísticas y reportes, CRM interno y almacén. Funciona en la nube y, para eventos sin
internet, con un **servidor local en Windows** que se sincroniza con la nube.

Privacidad por diseño (Ley 1581 de 2012): el rostro solo se usa con la **autorización explícita y registrada de la persona** (nunca por casilla del operador),
los menores de edad quedan fuera del reconocimiento facial, el rostro se **borra 7 días después de finalizado el evento** y cada persona puede revocar o pedir la
supresión de sus datos. Textos legales: `docs/legal/`.

> **Dónde está cada cosa.** Reglas técnicas del código: [`CLAUDE.md`](CLAUDE.md). Decisiones del dueño: [`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`](docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md).
> Cómo se trabaja (ramas, commits, pruebas, «hecho»): [`CONTRIBUTING.md`](CONTRIBUTING.md). Qué cambió y cuándo: [`CHANGELOG.md`](CHANGELOG.md).
> Índice de la documentación técnica: [`docs/00_README.md`](docs/00_README.md).

## Para quien evalúa la plataforma (cliente o empresa interesada)
- **Qué resuelve:** registrar e identificar personas en eventos sin planillas ni tarjetas, imprimir escarapelas al instante, controlar quién entra a qué zona
  y entregar reportes al cliente al cerrar el evento.
- **Cómo se identifica a la persona:** cédula (lector o cámara), QR de la escarapela digital o reconocimiento facial, siempre con consentimiento previo.
- **Dónde corre:** Google Cloud Run (región `us-east4`), base de datos PostgreSQL en Neon, archivos en Cloud Storage, dominio `app.golden-eventos.com`.
  Sin internet: servidor local en una laptop Windows con instalador propio y llaves de producto.
- **Multiempresa (SaaS):** cada cliente es un *tenant* aislado por datos; la plataforma se está preparando para ofrecerse como servicio a otras empresas
  (decisión del 22-nov-2026; ver `docs/revision_2026-11-22/`). El CRM es interno de Golden y no forma parte del servicio.
- **Datos personales:** consentimiento explícito, cifrado del vector facial, retención de 7 días, supresión y revocación disponibles, registro inmutable de aceptaciones.

## Para quien va a programar
### Stack
FastAPI + SQLAlchemy síncrono + PostgreSQL (Neon, pooler en modo transacción) + Alembic (migraciones a mano, id ≤ 32 caracteres). Frontend Jinja2 + JavaScript plano
(sin framework, sin build), diseño por tokens `--gw-*` (`static/css/design-system.css`). Motor facial `face_recognition`/dlib en procesos hijo. Cola de trabajos en Postgres
(`app/jobs.py`) y Cloud Run Jobs para lo largo. Tres servicios de **una** imagen (`publico`, `web`, `biometria`) elegidos por `APP_MODE`.

### Requisitos
- Python 3.13 (local y CI; la imagen de Cloud Run usa 3.14) y PostgreSQL 14 o más reciente.
- Node 22 solo para las pruebas de JavaScript (`npm ci` instala jsdom).
- Opcionales: **Tesseract OCR** (lector de la cédula nueva) y `cmake` + compilador C++ para `dlib` (las pruebas no lo necesitan: usan un doble del motor).

### Arranque local
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # completa DATABASE_URL y SECRET_KEY (hay comentarios dentro)
createdb golden_db
alembic upgrade head
python scripts/create_staff_user.py --username admin --role super_admin
uvicorn app.main:app --reload --port 5000             # http://localhost:5000
```
Sin correo configurado, los correos quedan como `.eml` en `data/outbox/`.

### Pruebas
```bash
ruff check .                                           # reglas básicas en todo el repo (el CI lo exige)
python -m pytest -q                                    # ~3.600 pruebas; base aparte golden_test (se crea sola) con las migraciones reales
python3 -m pytest --noconftest -q tests/<archivo>.py   # las puras y de texto, sin base (≈1.500)
npm ci && for f in tests/js/*_check.js; do node "$f" || break; done   # 99 comprobaciones de JS (17 con jsdom)
```
La suite completa corre en GitHub (`.github/workflows/ci.yml`) con Postgres de servicio. Las ramas `diag/**` solo corren `diag.yml`.

### Mapa del repositorio
```
app/              FastAPI: main.py (app y middlewares), models.py, auth.py, routers/ (una ruta por módulo), crm/, entrypoints/
alembic/versions/ migraciones (0001 … 0161), escritas a mano
templates/        páginas Jinja2 (kiosk_*.html = pantallas del evento; form_public.html = formulario público)
static/js|css     JavaScript y CSS de las páginas; design-system.css es la única fuente de colores y tamaños
tests/            pytest (+ tests/js con Node); conftest.py crea la base de pruebas y el doble del motor facial
scripts/          utilidades (crear staff, respaldos, migraciones de datos, pruebas de carga, visual_harness)
deploy/gcp        bootstrap, deploy y configuración de Cloud Run (lee deploy/gcp/README.md antes de desplegar)
deploy/windows    instalador del servidor local (Inno Setup + PowerShell)
deploy/local      docker-compose y entorno de ensayo
docs/             documentación técnica; índice en docs/00_README.md
```

### Despliegue (resumen; el detalle manda en `docs/19_GUIA_PRODUCCION.md` y `deploy/gcp/README.md`)
1. Rama propia → **staging primero** (`deploy/gcp/manual_deploy.sh staging …`, lo corre el dueño en Cloud Shell). Staging se apaga al terminar (`staging_power.sh off`).
2. Suite completa de GitHub una sola vez, al final, cuando el dueño aprobó staging.
3. Producción solo con autorización explícita para ese commit, con respaldo (rama de Neon `antes-produccion-<fecha>`) antes y verificación en `/sistema` después.
4. `main` no es la fuente de producción hoy: lo desplegado se ve en `/sistema` («Versión desplegada») y en `CHANGELOG.md`.

Lo heredado de la VM anterior (`deploy/gunicorn.conf.py`, `deploy/nginx-golden.conf`, `.github/workflows/deploy.yml`) se conserva hasta que el dueño confirme el cierre de la VM:
ver `deploy/LEEME.md`.
