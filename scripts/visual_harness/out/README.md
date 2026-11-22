# Salidas del arnés visual (no se versionan)

Esta carpeta guarda las **capturas de pantalla** (`*.png`) que genera `scripts/visual_harness/shoot.py` al recorrer las
páginas de muestra (`pages*.py`, con los datos ficticios de `mocks*.py`) en varios anchos y en modo claro y oscuro.

- Son **salidas**: se regeneran en cada corrida y cambian con cualquier ajuste visual. Por eso están en `.gitignore`
  desde el 22-nov-2026 (antes pesaban 57 MB en 234 archivos dentro del repositorio).
- Para generarlas: `pip install -r requirements-dev.txt && playwright install chromium`, y luego
  `python scripts/visual_harness/shoot.py` (ver los argumentos al inicio de ese archivo).
- No contienen datos reales: todo sale de los datos de muestra del arnés.
- Si una captura debe quedar como referencia permanente, cópiala a `docs/ux/` con un nombre que diga qué muestra.
- Las capturas anteriores siguen en el historial de git (cualquier commit previo al 22-nov-2026).
