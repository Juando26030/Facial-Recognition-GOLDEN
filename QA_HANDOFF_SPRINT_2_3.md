# Handoff de QA — Sprint 2.3

Reporte para quien vaya a probar este cambio (otra sesión/bot o Juan David directamente). Rama: `sprint2/reverify-fixes-and-badges`. **No está mergeado a `main`** — no mergear sin que Juan David lo pruebe primero y dé el visto bueno explícito.

## Qué se pidió y qué se hizo

1. **Parámetros del Evento: agregar campo opcional + que salga en el reporte.**
   Hecho. Nuevo botón "+ Agregar campo opcional" en `/kiosk/{event_id}/parametros`. El reporte Excel (`GET /api/report?event_id=...`) ahora trae una columna por cada opcional rotulado del evento. De paso se corrigió un bug real: el reporte mezclaba personas de TODOS los eventos del cliente en vez de solo el evento pedido — ya quedó scoped por evento.

2. **Cédula editable en una persona ya registrada.**
   Hecho, **solo para `admin`/`super_admin`**. En el modal "Editar" del Directorio, sección nueva "Corregir cédula" con su propio botón "Aplicar" y confirmación. Ojo: corregir la cédula afecta a esa persona en TODOS los eventos del mismo cliente (no solo el actual), porque `User` se comparte entre eventos — se avisa en el propio modal.

3. **Quitar el "1." de la pestaña "Registro" cuando es la única.**
   Hecho. Solo aplica a eventos sin biometría (una sola pestaña). Con biometría activa sigue "1. Escáner de Acceso" / "2. Registro".

4. **Menú lateral (Clientes / Eventos / Calendario / Configuración).**
   Hecho para `coordinador`/`admin`/`super_admin`, visible en toda la app. `digitador`/`cliente` NO lo tienen (cuentas temporales, como ya era antes con cualquier navegación de "volver"). Se eliminaron los botones `← Métodos`/`← Panel` de los 8 templates que los tenían — queda el atrás del navegador + este menú.
   - `/clientes`: árbol Cliente→Eventos (lo que antes vivía combinado en el Panel), búsqueda SOLO por nombre de cliente.
   - `/eventos`: lista plana de eventos, búsqueda por nombre/código + filtro de estado (Creado/En Proceso/Finalizado).
   - `/calendario`: placeholder explícito, sin funcionalidad — pendiente definir con Juan David en otra ronda.
   - `/configuracion` (**admin+ solamente**): pestaña "Apariencia" (color de acento + tipografía) y pestaña "Staff y Permisos" (la gestión de staff de siempre, embebida).

5. **Tesseract sigue dando 503 en "Escanear foto de cédula nueva".**
   Esto **no es un bug de código** — el servidor de producción no tiene el binario de Tesseract OCR instalado (confirmado varias veces en rondas anteriores). Esta vez se arregló de raíz: `.github/workflows/deploy.yml` ahora instala `tesseract-ocr` automáticamente en cada deploy. **No se puede verificar en este sandbox** (no hay VM real) — hay que confirmarlo después del primer deploy real a producción probando ese mismo flujo.

6. **Apariencia (color/tipografía) es por computador, no por cuenta.**
   Confirmado explícitamente con Juan David: se guarda en `localStorage` del navegador, nunca en la base de datos. Si prueban desde otro computador o borran datos del sitio, vuelve al dorado por defecto — es el comportamiento esperado, no un bug.

## Bug real encontrado (no pedido, corregido de todas formas)

`kiosk_entry` en `app/main.py` (la ruta que resuelve cuando un `cliente` con exactamente un evento autorizado entra a la app) rompía el JavaScript de la página de Registro — un `cliente` en esa situación específica se topaba con una página con la mitad de la funcionalidad rota (el script fallaba en silencio). Corregido y cubierto por test.

## Cómo levantar el entorno de prueba

No hay Postgres en este sandbox — se puede probar igual con SQLite:

```bash
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./prueba_local.db"
export SECRET_KEY="dev"
alembic upgrade head
python scripts/create_staff_user.py --username admin --role super_admin
uvicorn app.main:app --reload --port 8000
```

Con Postgres real (recomendado si es posible, para que el flujo sea idéntico a producción): usar el `.env` normal del proyecto y correr `alembic upgrade head` antes de levantar el servidor — la migración nueva es `0014_event_field_configs` (de la ronda anterior) y no hay migraciones nuevas en esta ronda (Sprint 2.3 no tocó el esquema de base de datos).

## Qué probar (ver `TESTING.md`, sección 21 — "Sprint 2.3")

24 casos puntuales, IDs `S23-01` a `S23-24`. Los más importantes para probar en vivo (ya verificados por mí con `TestClient` + navegador real, pero conviene que un segundo par de ojos los confirme con datos reales de Juan David):

- **S23-17/S23-18** — cédula editable: corregir una cédula real que se sabe que está mal, confirmar que la persona se sigue reconociendo (por cédula Y por cara, si el evento es biométrico) con el número nuevo.
- **S23-15/S23-16** — reporte: agregar un opcional nuevo desde Parámetros, cargarle datos a un par de personas, descargar el reporte y confirmar la columna. Si el cliente tiene más de un evento, confirmar que el reporte de cada evento no mezcla gente del otro.
- **S23-24** — Tesseract: esto es lo único que NO se puede confirmar aquí. Después del próximo deploy a producción, probar "Escanear foto de cédula nueva" y confirmar que ya no da 503.
- **S23-01/S23-02** — sidebar: confirmar con una cuenta `digitador`/`cliente` real que efectivamente no ven el menú nuevo (son cuentas creadas desde "Usuarios del Evento" dentro de un evento).

## Verificación ya hecha en este sandbox

- `TestClient` (FastAPI, SQLite en memoria con `PRAGMA foreign_keys=ON`): 64 aserciones en total entre los tres scripts de esta ronda + la ronda anterior de Parámetros, todas en verde.
- Sweep de render Jinja de los 29 combos página×rol relevantes (incluye las 4 páginas nuevas y los 8 templates que ganaron el sidebar), sin errores.
- `node --check` en todo el JavaScript nuevo/tocado.
- Navegador real (servidor local + SQLite): sidebar visible/resaltado para coordinador+, ausente para digitador; cajón off-canvas en móvil; Apariencia se aplica al instante y persiste entre páginas del mismo navegador; pestaña "Staff y Permisos" embebida sin header duplicado; búsqueda de Clientes y de Eventos (con filtro de estado); cédula editable de punta a punta (cambio real persistido, reflejado en el Directorio); "Registro" sin numerar en evento sin biometría, numerado en evento con biometría; "+ Agregar campo opcional" en Parámetros sin recargar la página.

## Qué sigue pendiente (fuera del alcance de esta ronda)

- El bug de "subí un Excel con Juan David y Juliana pero solo quedó Juan David" — sigue bloqueado, hace falta que Juan David reenvíe el archivo real que usó (el que mandó antes era solo la plantilla en blanco con un ejemplo).
- Diseño real de Calendario — queda como placeholder hasta que Juan David defina cómo debe funcionar.
