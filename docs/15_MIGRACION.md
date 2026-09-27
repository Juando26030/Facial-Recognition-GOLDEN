# Migración a Cloud Run + Neon (Fases 1-2)

Rama `migra/fase1-2`. Plan y decisiones de fondo: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` (§4-8, §11, §14-16).
Este archivo se completa en la sesión 3 (runbook del día del cambio + costos); por ahora lleva la lista de progreso.

## Progreso (se actualiza en cada commit)

### Sesión 1 — la app queda lista para Cloud Run + Neon
- [ ] 1. Cupo atómico: `form_reserve_slot()` (migración 0049) + wrapper en `formsvc` + `_submit` + pruebas de concurrencia
- [ ] 2. `GcsStorage` en `app/storage.py`
- [ ] 3. Backend Cloud Tasks en `app/jobs.py` (Postgres sigue como alternativa)
- [ ] 4. Directorio paginado e incremental en `static/js/directory.js`
- [ ] 5. Dockerfile multi-etapa + 3 puntos de entrada, construido y probado con Docker en local
- [ ] 6. `.env.staging.example` + `.env.staging` en `.gitignore` → migraciones y contenedor contra la rama `staging` de Neon

### Sesión 2 — pendiente
`deploy/gcp/bootstrap.sh`, staging en Cloud Run + workflow de GitHub Actions, jobs programados (respaldos, purga,
check_backups, precalentamiento, congelamiento de despliegues), scripts de migración VM→Neon/GCS con verificación.

### Sesión 3 — pendiente
Prueba de carga distribuida, medición de latencia, este documento completo (runbook + costos), CLAUDE.md, revisión final.

## Decisiones tomadas
- `docs/13` se actualizó con la versión completa que Juan David pegó en el chat (§14-§17); no estaba en el disco.
- Cupo atómico: la función cuenta `form_submissions` directamente (confirmadas + en pago dentro de 30 min), igual que
  `held_count`. Códigos de descuento y la purga de inscripciones abandonadas quedan fuera de la función a propósito
  (no necesitan el bloqueo de la fila del formulario).
