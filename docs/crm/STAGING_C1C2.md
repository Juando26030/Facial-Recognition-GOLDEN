# Staging C1c-2 — importar oportunidades, actividades, productos, cotizaciones y proformas

Con `CRM_ENABLED=1` y `CRM_IMPORT_APPLY=1` (solo staging). Archivos **sintéticos**: `python scripts/crm_make_synthetic_suitecrm.py /tmp/sint 30` (8 CSV). Producción sigue apagada; datos reales NO hasta que Juan David lo diga y la auditora haya recibido el aviso.

## Criterios
1. `/crm/importar` muestra 8 campos de archivo (cuentas, contactos, productos, oportunidades, actividades, cotizaciones, líneas, proformas).
2. «Muestra» con los 8 archivos: lee 20 filas por archivo y no guarda nada (conteos en cero en las tablas `crm_*`).
3. «Prueba completa»: contactos, oportunidades y cotizaciones salen con `sin cuenta conocida = 0` aunque la base esté vacía (las cuentas vienen en los archivos). Informe con conteos y sin ningún nombre ni importe.
4. Subir un CSV al que le falta la columna obligatoria → error claro al subir, sin corrida creada.
5. «Cargar de verdad» sin prueba completa, con otros archivos, o sin escribir CARGAR → rechazado; con `CRM_IMPORT_APPLY=0` → 403.
6. Carga real: 10 productos, 30 oportunidades, 30 cotizaciones, 15 proformas; las oportunidades «Closed Won» quedan ganadas **sin evento ni cliente nuevos**.
7. Cotización `sint-qte-0001`: subtotal 1.150.000, descuento 100.000, impuesto 218.500, total 1.368.500 (lo calcula el servidor). La `…0005` (solo total) queda en 1.190.000 con una línea «Total importado».
8. Repetir la misma carga no duplica nada (idempotente).
9. Un número nuevo de cotización/proforma/evento creado después sale por encima del mayor importado.
10. Los archivos de `crm/imports/<id>/` ya no existen al terminar. Ningún dato personal en logs ni en el informe.

Pruebas: `tests/test_crm_importer_mas_puro.py` (texto, pasan) y `tests/test_crm_importer_mas.py` (con base, SIN EJECUTAR).
