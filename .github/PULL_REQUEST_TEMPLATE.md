<!-- Un PR = una pieza. Título: «Área: qué cambia» (máx. 72 caracteres). Reglas: CONTRIBUTING.md -->

## Qué cambia y para quién
<!-- Dos o tres líneas en español claro, pensadas para Juan David: qué ve distinto la persona que usa la pantalla. -->

## Por qué
<!-- La decisión o el problema real (fecha de la decisión si la hubo). -->

## Migraciones
- [ ] No toca el modelo de datos
- [ ] Migración `NNNN_...` incluida, id ≤ 32 caracteres, una sola cabeza (`alembic heads`), solo agrega (o explica por qué no)

## Pruebas
- [ ] `ruff check .` limpio
- [ ] Pruebas puras / de texto en verde: `python3 -m pytest --noconftest -q tests/<archivo>.py`
- [ ] Suite completa con base (`python -m pytest -q`) — en GitHub, UNA vez al final, cuando el dueño aprobó staging
- [ ] Pruebas de JS (`tests/js/*_check.js`) si tocó `static/js/`
- [ ] Prueba de comportamiento nueva para el flujo que cambió (no solo prueba de texto)

## Reglas inamovibles tocadas
- [ ] No toca impresión, textos legales, biometría ni consentimiento
- [ ] Si toca alguna: enlace a la autorización escrita de Juan David

## Visual
- [ ] Solo tokens `--gw-*` / clases `.gw-*`; barrido de 320 a 3440 px sin desplazamiento horizontal
- [ ] Capturas (sin datos personales) si cambió una pantalla

## Documentación
- [ ] Entrada en `CHANGELOG.md`
- [ ] `CLAUDE.md` actualizado si cambió arquitectura o una regla
- [ ] Documento de la pieza en `docs/` (o enlace al existente)

## Qué NO se pudo comprobar
<!-- Obligatorio. Sin inventar: «no hay Postgres en este entorno», «falta la prueba física con la QL-800», etc. -->

## Despliegue
- [ ] Probado en staging por Juan David
- [ ] Respaldo de Neon antes de producción (`antes-produccion-<fecha>`)
- [ ] Verificado después en `/sistema` («Versión desplegada» = este commit)
