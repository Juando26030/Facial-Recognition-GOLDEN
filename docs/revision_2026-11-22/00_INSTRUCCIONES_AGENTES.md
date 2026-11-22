# Instrucciones comunes para los agentes de la revisión integral (22-nov-2026)

Eres un agente con un ROL concreto (lo dice tu encargo). Trabajas sobre el repositorio `/home/claude/facial-recognition-golden`,
rama `saas/revision-integral` (ya está en el working tree; NO cambies de rama, NO hagas commit, NO hagas push: lo hace el coordinador).
El sitio web corporativo está en `/home/claude/golden-sitio-web` (Astro, commit 6eb6b6a).

## Antes de empezar (obligatorio)
1. Lee `CLAUDE.md` y `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md` completos.
2. Lee lo que tu rol necesite: `docs/13_ARQUITECTURA_ESCALABILIDAD.md`, `docs/19_GUIA_PRODUCCION.md`, `deploy/gcp/README.md`,
   `docs/17_SERVIDOR_LOCAL.md`, `docs/16_BACKLOG_PRODUCTO.md`, `docs/ux/ESTANDARES_VISUALES.md`, `docs/historial.md` (grandes), `app/auth.py`,
   `app/main.py`, `app/routers/`, `templates/`, `static/js/`, `tests/`, `deploy/windows/` (instalador local), `.github/workflows/`.

## Límites (INAMOVIBLES)
- Nada a `main`, ningún merge, ningún despliegue, ningún comando de nube (`gcloud`, `firebase`, `neon`), ningún cambio de DNS. No borres ramas.
- Nada de secretos ni datos personales reales en archivos, logs ni reportes. El repo es PÚBLICO.
- No escribas malware ni exploits armados. Un análisis de seguridad describe la debilidad, cómo se comprobó sin dañar nada y cómo se arregla.
- No hay red desde Bash hacia internet (ni pip ni npm instalan). Usa lo instalado. Python 3, Node, Playwright y Chromium sí están.
- La única dirección viva autorizada para pruebas es STAGING (`https://staging.golden-eventos.com`), y solo desde las herramientas de navegador
  si tu encargo lo dice; nunca producción (`app.golden-eventos.com`). Nunca contraseñas: la sesión ya está abierta o no se prueba.
- Si cambias código: cambios pequeños, seguros, con prueba (pytest sin base: `python3 -m pytest --noconftest -q tests/<archivo>.py`; `ruff check .`),
  respetando `CLAUDE.md` (endpoints `def`, tokens `--gw-*`, mensajes en español, identificadores en inglés). Solo toca archivos de TU área
  (tu encargo la define) para no chocar con otros agentes que trabajan a la vez. Si un cambio es grande o riesgoso, NO lo hagas: descríbelo en el reporte con el plan exacto.
- No toques `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`, `app/legal_texts_data.py`, ni nada de impresión o textos legales.

## Entregable: UN archivo Markdown en `docs/revision_2026-11-22/<NN>_<rol>.md` (el nombre lo dice tu encargo), en español claro, para un dueño NO técnico
Estructura obligatoria:
1. **Resumen en 5 líneas** (qué tan bien está, lo más grave, lo más valioso).
2. **Hallazgos**: tabla con columnas `#`, `Severidad` (Crítica/Alta/Media/Baja), `Qué pasa`, `Dónde` (archivo o pantalla), `Por qué importa`, `Qué se hizo` (Corregido / Propuesto / Pendiente).
3. **Qué se cambió en el código** (lista de archivos y qué hace cada cambio; si nada, dilo).
4. **Qué queda pendiente y por qué** (con estimación en horas y orden recomendado).
5. **Qué NO se pudo comprobar** (sin inventar).
6. **Consejo en corto** (cinco voces de una línea: contrario, primeros principios, expansionista, forastero, ejecutor) y **veredicto** con UN siguiente paso.
Sé concreto: rutas, nombres de pantallas, números. Nada de generalidades.
