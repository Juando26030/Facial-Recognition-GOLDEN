# Desplegar a producción (solo a mano)

Desde el 21 de octubre de 2026 **ningún push ni merge a `main` despliega producción**. Este repositorio no ofrece «Required reviewers» en el Environment `production`, así que la decisión de desplegar queda en el propio flujo (`.github/workflows/cloudrun.yml`).

**Para desplegar:** GitHub → Actions → «Cloud Run (staging y producción)» → **Run workflow** → Branch: **`main`** → en **confirm** escribe `DESPLEGAR` (mayúsculas) → Run.
- Corre `test` y, si pasa, el job `production` (imagen, migraciones, 3 servicios, Jobs y Firebase).
- Respeta el congelamiento: si hay un evento «En Proceso» o uno que abre en menos de 3 horas, se detiene. Casilla **force** solo en emergencias (salta únicamente esa consulta; no salta las pruebas).
- Otra rama, o `confirm` vacío o distinto de `DESPLEGAR`: el job `production` no se ejecuta.

**Qué pasa con un push o merge a `main`:** solo corre el CI de `ci.yml` (pruebas, ruff, imagen), que tiene su propio disparo. No hay despliegue.

**Staging** sigue igual: cada push a `migra/fase1-2` lo despliega.

**Primer despliegue (ya hecho, 21 oct):** se lanzó así con `force` porque el servicio aún corría la imagen de relleno y no respondía `/api/ops/deploy-allowed`.

Protección de la prueba: `tests/test_cutover_workflows.py` evalúa la condición del job `production` para todas las combinaciones (push, pull request, otra rama, sin confirmar, texto distinto) y falla si algo distinto de «lanzado a mano en `main` con DESPLEGAR» llega a producción.
