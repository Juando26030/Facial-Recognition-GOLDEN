# PR candidato → main (NO fusionar hasta «DESPLIEGA PRODUCCIÓN»)

**Rama:** `candidato/produccion-29oct` → `main` (avance directo: `main` = `6c71cc3` es ancestro del candidato).
**Código:** idéntico a `d53498e` (`migra/fase1-2`, **ya probado en staging el 29-oct-2026**). El candidato solo agrega documentación y scripts: la sección del 29-oct de `docs/13_RUNBOOK_PRODUCCION.md` y `deploy/produccion_29oct/`.

## Título del PR
Producción 29-oct-2026: exportar/importar eventos y arreglo de impresión (d53498e) [skip ci]

## Texto del PR
Lleva a `main` lo que está en staging (`d53498e`):
- **Exportar e importar eventos** entre entornos (solo super_admin): paquete `.zip`, simulacro, informe «Origen vs Destino», biometría opcional cifrada, archivos del storage, descarga firmada de 5 min y borrado a las 24 h (`docs/18_EXPORTAR_EVENTOS.md`).
- **Arreglo de impresión:** página SIEMPRE de 62 × 99,8 mm, imagen de máximo 96 mm, horizontal con recorte centrada a lo largo de la tira (`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`, `tests/test_impresion_parametros_fijos.py`).
- **Migraciones 0074 y 0075**, solo aditivas (dos tablas nuevas, una columna nueva y columnas nuevas en una tabla de bitácora). Ensayadas bajando y subiendo sobre una copia con datos sintéticos.
- `CONTINGENCY_ENABLED=1` en producción (sin cambios respecto de hoy).

**Fusionar este PR NO despliega producción.** El despliegue es manual: Actions → «Cloud Run» → rama `main` → `confirm=DESPLEGAR`. Plan de vuelta atrás y respaldo: runbook, sección del 29-oct. Solo se fusiona tras la frase «DESPLIEGA PRODUCCIÓN» de Juan David.

[skip ci]

## Mensaje del commit de fusión (si se fusiona con «Create a merge commit» o «Squash»)
```
Producción 29-oct-2026: exportar/importar eventos y arreglo de impresión (d53498e)

[skip ci]
```
(`[skip ci]` evita una corrida de pruebas redundante sobre `main`: el candidato ya pasó la CI completa.)
