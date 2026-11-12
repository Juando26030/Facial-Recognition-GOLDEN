# CRM — consultas a la base por pantalla

C1a no tiene pantallas. Desde C1b cada pantalla anota aquí cuántas consultas hace (regla 6 de ahorro del documento 50: medir y dejar la cifra) y el motivo.

| Pantalla | Pieza | Consultas | Cómo se midió | Nota |
|---|---|---|---|---|
| (vacía hasta C1b) | | | | |

## C3
- `/crm/cotizaciones`: 1 consulta de lista paginada + `/quotes/meta` (catálogo en memoria) + `/filters`. Sin sondeos.
- `/crm/cotizaciones/{id}`: detalle (cotización + líneas + versiones), `/quotes/meta`, contactos de la cuenta, historial. Al guardar: 1 escritura. El PDF se genera solo al pedirlo.
- `/crm/productos` (admin): productos paginados + condiciones + plantillas.
- `/crm/buscar`: 5 consultas con LIMIT 8, solo al pulsar «Buscar».
