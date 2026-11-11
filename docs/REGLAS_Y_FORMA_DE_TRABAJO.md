# Reglas de Juan David y forma de trabajar con él

Juan David es el dueño de GoldenWeb 2.0 / Golden Eventos y Logística S.A.S. No es técnico. Vive en Bogotá (UTC-5), habla español. Estas reglas las puso él (muchas, después de un tropiezo real) y mandan sobre cualquier hábito.

## 1. Formato de cada respuesta («LLM Council»)
En todas las conversaciones, proyectos y sesiones de código, responder así (preferencia guardada en su perfil):
- **Dónde estamos** (qué pasó, en simple).
- **Consejo, en corto**: seis voces, una línea cada una: **Contrario** (qué puede fallar), **Primeros principios** (rompe supuestos), **Expansionista** (potencial que se pierde), **Forastero** (no sabe de la industria), **Ejecutor** (qué se hace el lunes por la mañana), **Presidente** (veredicto final). Los asesores se revisan entre sí sin saber quién escribió qué; el presidente decide.
- **Siguiente paso**: UNA acción concreta.
- Español claro, sin jerga. Si hay un comando, va completo, listo para copiar y pegar, **de a uno por mensaje** (una vez pegó tres juntos —`off`, `status`, `on`— y dejó staging encendido).

## 2. Autorizaciones (innegociables)
- **Nada a `main`, ningún merge, ningún despliegue a producción y ninguna migración en producción sin autorización explícita de Juan para ESA acción.** Una autorización no se generaliza (el «sí» del 11-nov 18:18 fue para el commit `0899e02`).
- Antes de producción: **respaldo** (rama Neon del proyecto «goldenweb PRODUCTION» con padre `production`, «datos y esquema», auto-borrado a 7 días). Después: verificar en `/sistema` la versión desplegada.
- **No crear recursos de nube ni correr `gcloud`/despliegues desde la sesión de Claude**: los comandos de nube los pega Juan en la Cloud Shell. Excepción: lo que él pida expresamente en el chat (el 11-nov pidió que Claude creara la rama de respaldo de Neon desde el navegador).
- **No modificar IAM/seguridad**: lo hace él. Nunca usar `FORCE=1` sin avisarle (salta el congelamiento por eventos en curso).
- **Secretos** nunca en el repo ni en el chat: solo nombres de variables; van a `.env`/`.env.staging` (ignorados) o a Secret Manager. Contraseñas de acceso: **las escribe Juan**; Claude nunca teclea contraseñas.
- Nada de fotos, encodings ni datos personales reales en repo, logs o commits. Resultados solo agregados. Pruebas de carga nunca contra producción.
- Lo que hace en commits: un commit + push por pieza terminada (con sus pruebas), y los commits terminan con las líneas de atribución que dé la sesión.

## 3. Dónde corre cada cosa (regla del 11-nov)
- **Solo la Cloud Shell DUEÑA** (`juando02603@…`), con el clon `~/gw-hosting`. La cuenta `juando02603spam@` ya no se usa para comandos (no tiene permiso de Hosting).
- Explicar «desde cero» dónde se abre la terminal y qué se pega; confirmar el resultado leyendo lo que él pega (`tail -n 25 ~/deploy-<entorno>.log` debe decir «LISTO (<entorno>, commit <SHA>)»).
- **Todo lo que se pueda hacer en el navegador, lo hace Claude** (revisar `/sistema`, crear rama de respaldo, probar pantallas). Juan deja la sesión abierta; si la sesión expira, él inicia sesión: Claude no. Preferido: navegador integrado de la app.
- Staging queda APAGADO por defecto (`bash deploy/gcp/staging_power.sh off`; encender solo al probar: `on`, y volver a `off`). Motivo: costos de Neon.

## 4. Visual y producto
- Todo lo visual sigue `docs/ux/ESTANDARES_VISUALES.md` (tokens `--gw-*`, clases `.gw-*`, nada suelto) y `docs/ux/LECCIONES_VISUALES_NOV11.md`.
- **Impresión INAMOVIBLE** (Brother QL-800, 62 × 99,8 mm, Chrome normal con su cuadro de impresión, nunca `--kiosk-printing`): `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`; solo cambia si Juan lo pide y se repite la prueba física.
- Biometría solo con consentimiento expreso de la persona, registrado en `audit_consent_logs`; borrado a los 7 días de terminado el evento; menores de 18 sin biometría; textos legales LITERALES de la auditora (no se editan).
- Pedidos de Juan suelen traer varias cosas a la vez («arregla lo visual en todas las pantallas»): hacerlas todas, por piezas, avisando al terminar cada entrega.

## 5. Cómo se verifica una entrega
1. `ruff check .` y las pruebas que corran sin base (`python3 -m pytest -q --noconftest tests/<archivo>.py`; en el entorno de Claude no hay Postgres/fastapi: las de base fallan por falta de fixture, es normal).
2. Pruebas de texto nuevas en `tests/test_ajustes_nov12.py` (patrón: leen el código fuente).
3. Revisión visual con `scripts/visual_harness/` (ver `docs/ux/LECCIONES_VISUALES_NOV11.md`).
4. Staging y/o producción: Juan lo usa; Claude lee `/sistema` y las pantallas con la sesión abierta.
5. Al terminar, decir qué NO se pudo comprobar (nada de afirmar lo que no se vio).

## 6. Errores que ya pasaron (para no repetirlos)
- Pegar el despliegue en la terminal equivocada (la otra cuenta no tiene el repo) → una sola terminal.
- Pegar varios comandos juntos → de a uno.
- Decir «staging está encendido» sin comprobarlo: el despliegue NO cambia el estado de la tarea horaria; verificar con `status`.
- Subir a producción cambios de un commit sin que Juan los hubiera probado: solo cuando él lo pide así, y con respaldo.
