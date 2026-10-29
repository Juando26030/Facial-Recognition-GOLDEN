# Relevo — 5 problemas de impresión/sesión vistos en producción (29-oct-2026)

Rama: **`fix/impresion-compartida-29oct`** (cortada de `main` = `b36bf92`, que es lo que corre producción). **No se ha tocado `main`, staging ni producción.** Reglas: nada a `main`, ningún despliegue ni migración en producción sin la frase «DESPLIEGA PRODUCCIÓN»; validar primero en staging; respetar `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` y `tests/test_impresion_parametros_fijos.py` (página 62×99,8 mm, imagen máx. 96 mm, margen izquierdo 0,5 mm, marca de fin, nunca `--kiosk-printing`).

## Estado

| Problema | Estado | Qué quedó |
|---|---|---|
| **A** sesión única del anfitrión | ✅ hecho y empujado (`5e08549`) | `app/sessions.py`: una cuenta con `PrintRoute.printer_staff_id` apuntando a ella y señal de su equipo en 60 s rechaza un 2.º inicio de sesión en OTRO dispositivo (`HOST_BUSY_MSG`); mismo navegador, sin señal 60 s y `force_release` del admin lo permiten; admin multi-sesión y cuentas que no atienden a nadie sin cambio. 3 pruebas. |
| **B** quién puede ser anfitrión / aviso falso | ✅ hecho y empujado (`5e4e603`) | Migración **`0076_print_mode`** (`print_devices.print_mode` = usb\|dialog\|none). El latido manda `print_mode`; control nuevo en la barra «Este equipo imprime con la ventana de Chrome» (`localStorage gw_print_dialog`). `_can_host` = en línea Y (usb o dialog); `set_route` rechaza `none` con razón; Parámetros trae `ineligible_reason`/`print_mode`. Se quitó «DESCONECTADA». Pruebas de servidor + `tests/js/shared_print_host_mode_check.js`. |
| **D** «Imprimir pendientes» abre una ventana por escarapela | ✅ implementado y probado en local (sin empujar hasta el commit de este relevo) | Servidor: `print-jobs-next?manual=1&batch=50` (reclamo por lote, arrendamiento de 4 min), `POST print-jobs/result-batch`, `POST print-jobs/release`. Página: `/kiosk/<evento>/escarapela/imprimir/<id>?users=a,b,c` arma UNA ventana con una hoja por persona (mismos parámetros inamovibles; la hoja 1 sale pixel a pixel igual a la de una sola persona). Cliente `shared-print.js`: `claimBatch` + `runBatchWindow` (confirma por trabajo DESPUÉS de la ventana, con «¿Salieron las N?»; si se cierra o dice que no → `release`). |
| **E** ventanas de impresión que se acumulan | ✅ implementado y probado en local | `badge-render.js`: `openPrintTab` con nombre fijo `goldenweb_print`, cierra la anterior, **sin `noopener`**; `kiosk_rostro.html` igual; `badge_print.html` se cierra sola con `afterprint` y por tiempo (3 min). |
| **C** márgenes distintos celular vs computador | ⏳ **PENDIENTE (no empezado)** | Ver «Qué falta». |

## Números medidos (Chrome real, base de demostración con datos ficticios; script `comp_de_check.py` descrito abajo)

- **D antes / después:** 3 personas en la ventana → antes **1 página** (solo la primera); ahora **3 páginas** de 62,1 × 99,8 mm, la 1.ª idéntica a la de una persona sola.
- **E antes / después (10 impresiones seguidas, emulación Pixel 7):** antes **10 ventanas abiertas** (máximo 10, al final 10); ahora **máximo 1** (y 0 al final cuando el navegador manda `afterprint`).

## Qué falta (en este orden)

1. **C — medir y igualar.** Escribir una prueba (Node/Playwright) que con la misma plantilla vertical y la misma horizontal calcule la trama final de AMBOS caminos (USB: `composeBitmap` → `prepareBitmap` con recorte + `cropMarginMm` 3 + `feedMm` 1,5; y Chrome: página 62×99,8, imagen ≤ 96 mm, izquierda 0,5 mm, marca de fin) y reporte ancho, alto, márgenes superior/inferior/laterales en mm, orientación y largo de papel. Después fijar como estándar lo que sale hoy en el computador (Chrome) y hacer que USB produzca el mismo margen superior, laterales y largo total con lógica compartida (`label-compose.js`/`ql-usb.js`, no dos copias). Ojo: un celular que imprime un trabajo ajeno usa `prefsForJob(job.prefs)` (los del que pidió), no los suyos. No cambiar los parámetros del camino Chrome. Documentar lo que el hardware no permita igualar y proponer una prueba física con regla.
2. **Pruebas físicas que debe hacer Juan en la Brother** (cuando todo esté en staging): computador (Chrome normal, vertical y horizontal), celular (USB), y anfitrión Windows con «Imprimir pendientes» de **5 escarapelas** (debe verse UNA ventana de Chrome con 5 hojas y, al terminar, «¿Salieron las 5?»).
3. **Docs:** actualizar `docs/historial.md` y `docs/15_MIGRACION.md` con los 5 problemas.
4. **Suite completa + ruff + `node tests/js/directory_paging_check.js`**, luego integrar a staging: la rama sale de `main`, que ya contiene staging (`d53498e`), así que `git push origin <rama>:migra/fase1-2` es avance directo (anunciar hash y punto de retorno antes de empujar). La migración **0076** se aplica sola en el despliegue de staging.
5. **Informe corto a Juan:** causa de cada problema, qué cambió, números de C (antes/después), pruebas, y riesgo de cada cambio para decidir si entra al piloto del viernes o espera (A, B, D, E tocan código en producción; 0076 es aditiva).

## Cómo retomar

```bash
cd C:\JDRJ\Golden\wt-compartida        # worktree de esta rama (si no existe: git worktree add ../wt-compartida fix/impresion-compartida-29oct)
git status; git log --oneline -6        # el último commit trae D y E
cp ../wt-staging-impresion/.env .env    # si falta (archivo ignorado por git)
# pruebas con base propia (la compartida golden_test puede estar en otra versión de Alembic):
export TEST_DATABASE_URL=".../golden_test_comp"
python -m pytest -q tests/test_impresion_compartida.py tests/test_puestos_sesiones.py tests/test_impresion_parametros_fijos.py
for f in tests/js/*check*.js; do node $f; done
```
Base de demostración con 0076: `golden_comp_demo` (copia de `golden_ux_demo` migrada); servidor de prueba: `uvicorn app.main:app --port 5095` con `DATABASE_URL` apuntando a esa base y `STORAGE_LOCAL_DIR` propio. Usuario de demostración local: `demo` (super_admin). Script de la medición D/E: `comp_de_check.py` (en la carpeta temporal de la sesión; si se perdió, reescribirlo: abre la página de impresión con `?users=` y mide páginas con `page.pdf`, y cuenta `context.pages` tras 10 `BadgePrint.printNow` en emulación móvil).
