# Golden Biometrics

Plataforma de registro y control de acceso a eventos de Golden Logísticas: carga de asistentes (Excel/CSV, con fotos
opcionales), registro por cédula, rostro o QR, escarapelas y certificados, control de áreas e inventario, reportes.
FastAPI + PostgreSQL + Alembic, reconocimiento facial con `face_recognition` (dlib), frontend server-rendered (Jinja2 + JS).

> El detalle técnico y las decisiones de diseño viven en [`CLAUDE.md`](CLAUDE.md). Los documentos de producto, en [`docs/`](docs/00_README.md).

## Requisitos
- Python 3.13+ y PostgreSQL 14+.
- **Tesseract OCR** (lector de la cédula nueva): `sudo apt-get install -y tesseract-ocr` (Linux) — o el instalador de UB Mannheim en Windows.
- `dlib` se compila al instalar `face-recognition`: necesita `cmake` y un compilador de C++ (en Ubuntu: `sudo apt-get install -y build-essential cmake`).

## Instalación local
```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # completa DATABASE_URL y SECRET_KEY (ver comentarios dentro)
createdb golden_db                  # o desde pgAdmin
alembic upgrade head                # crea/actualiza el esquema
python scripts/create_staff_user.py # crea el primer Super Admin
uvicorn app.main:app --reload --port 5000
```
Abre http://localhost:5000. Sin correo configurado (`.env`), los correos no salen: quedan como `.eml` en `data/outbox/`.

## Pruebas
```bash
pip install pytest httpx
python -m pytest -q
```
Corren contra una base **aparte** (`golden_test`, se crea sola en el mismo servidor que `DATABASE_URL`; nunca toca la de
desarrollo) y con un doble del motor biométrico, así que no necesitan dlib ni fotos. Cada corrida aplica las migraciones
desde cero. Requieren Node.js solo para las pruebas del lector de QR (si falta, se omiten).

## Producción (resumen)
- VM de Google Cloud: Nginx (TLS con Certbot) → uvicorn en `127.0.0.1:8000` (systemd: `facial-recognition`), detrás de Cloudflare.
  Configuración de referencia en [`deploy/`](deploy/).
- `ENVIRONMENT=production` y `SECRET_KEY` son obligatorias. Correo: Microsoft Graph (ver `.env.example`).
- **Deploy:** cada push a `main` corre `.github/workflows/deploy.yml`: pruebas (`ci.yml`) → `git reset --hard origin/main` en la
  VM → `pip install` → `alembic upgrade head` → reinicio del servicio con verificación de que responde.
- **Backups:** `scripts/backup_db.sh` (diario, con copia externa a Google Cloud Storage) y `scripts/restore_db.sh`
  (restaurar y verificar). Procedimiento completo en `CLAUDE.md`, sección "Backups y restauración".

## Estructura
```
app/            FastAPI: routers/, models.py, auth.py, security.py, mailer.py, biometrics.py, reports.py
alembic/        migraciones
templates/      páginas Jinja2
static/js/      JS de las páginas (directory.js, qr.js, badge-render.js, ...)
scripts/        crear staff, backup y restauración
deploy/         configuración de referencia de la VM (Nginx, systemd) y regla de retención del bucket
tests/          pruebas automáticas (pytest)
docs/           documentos de producto
```
