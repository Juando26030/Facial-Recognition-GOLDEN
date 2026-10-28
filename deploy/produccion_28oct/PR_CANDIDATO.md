# PR candidato → main (NO fusionar hasta «DESPLIEGA PRODUCCIÓN»)

**Rama:** `candidato/produccion-28oct` → `main` (avance directo: `main` = `b225a2d` es ancestro del candidato).
**Código:** idéntico a `79348da` (`migra/fase1-2`, staging del 28-oct-2026). El candidato solo agrega documentación y scripts: `docs/13_RUNBOOK_PRODUCCION.md` y `deploy/produccion_28oct/`.

## Título del PR
Producción 28-oct-2026: igual que staging (79348da) [skip ci]

## Texto del PR
Lleva a `main` el código que Juan David probó en staging el 28-oct-2026 (commit `79348da`): impresión (USB directo, ventana normal con la misma etiqueta, aviso de Windows), Registro touch, puestos de impresión y sesiones, origen de la persona y arreglos del Grupo A/B. Migraciones 0069–0073, solo aditivas (ensayo en `docs/13_RUNBOOK_PRODUCCION.md` §3).

- Los parámetros de impresión son inamovibles: `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` y `tests/test_impresion_parametros_fijos.py`.
- `CONTINGENCY_ENABLED=0` en producción (decisión; no cambia).
- **Fusionar este PR NO despliega producción.** El despliegue es manual: Actions → «Cloud Run» → rama `main` → `confirm=DESPLEGAR`. Plan de vuelta atrás y respaldo: runbook §1 y §7.
- Solo se fusiona tras la frase «DESPLIEGA PRODUCCIÓN» de Juan David.

[skip ci]

## Mensaje del commit de fusión (si se fusiona con «Create a merge commit» o «Squash»)
```
Producción 28-oct-2026: igual que staging (79348da)

[skip ci]
```
(`[skip ci]` evita una corrida de pruebas redundante sobre `main`: el candidato ya pasó CI completa.)
