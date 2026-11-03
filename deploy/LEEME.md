# `deploy/` — qué está vigente y qué es heredado

**Vigente (Cloud Run):** `gcp/` (bootstrap, deploy, config, env), `firebase/`, `docker-compose.yml`, `gcs-*.json`, `loadtest/`.
Los despliegues salen de `.github/workflows/cloudrun.yml` (staging al empujar `migra/fase1-2`; producción a mano desde `main`).

**Histórico (se conserva; no borrar):** `produccion_28oct/` y `produccion_29oct/` — scripts y notas de los pasos a producción de esas fechas
(los citan `docs/13_RUNBOOK_PRODUCCION.md` y `docs/19_GUIA_PRODUCCION.md`). Pendiente de 0B: extraer una plantilla única parametrizada
y probarla antes de mover nada (decisión del 30-oct).

**Heredado de la VM `golden-biometrics-prod` (Gunicorn + Nginx + Postgres local):** `gunicorn.conf.py`, `facial-recognition.service`,
`nginx-golden.conf` y `.github/workflows/deploy.yml`. No se usan en Cloud Run. **No se borran hasta que Juan David confirme por escrito que
la VM está cerrada.**
