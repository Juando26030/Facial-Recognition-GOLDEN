# Prueba en staging — C3 (productos, cotizaciones, proformas, búsqueda, filtros, exportación)

Solo con datos ficticios, en staging (`CRM_ENABLED=1`). Producción NO se toca.

## Antes
1. Correr las pruebas con base: `python -m pytest -q tests/test_crm_cotizaciones.py` (escritas, sin ejecutar) y, por si acaso, las demás `test_crm_*.py`.
2. Migración `0133_crm_quotes` aplicada en staging (`alembic upgrade head` con `DIRECT_DATABASE_URL`).
3. Los contadores `quote` y `proforma` nacen «no listos»: hacerlos listos como los de cuenta y evento (ver `docs/crm/CODIGOS.md`) antes de crear la primera cotización; si no, la API responde 409 con un mensaje claro.

## Criterios de éxito
1. `/crm/productos` (admin): crear un producto ficticio con precio e impuesto, editarlo, desactivarlo y volver a activarlo. Un código (SKU) repetido se rechaza.
2. En la misma pantalla: crear una condición y una plantilla del PDF (cotización y proforma); archivar la condición. La primera plantilla de cada tipo queda como predeterminada.
3. `/crm/cotizaciones` → «Nueva cotización»: buscar una cuenta, poner título y crear. Recibe el siguiente número y abre el editor.
4. En el editor: agregar una línea desde un producto y una línea libre; los totales de pantalla cambian al escribir. Al guardar, los totales que vuelven son los del servidor (subtotal = suma de netos, descuentos, impuestos, total).
5. Una línea con 3 × 10,01, 50 % de descuento y 19 % de impuesto da neto 15,02 e impuesto 2,85 (redondeo de mitad hacia arriba).
6. «Descargar PDF» abre un PDF con encabezado, líneas, totales y condiciones; las notas de la reunión NO salen. Cambiar algo y volver a pedirlo genera uno nuevo.
7. Etapas: borrador → enviada → negociada → aprobada/rechazada. Una enviada no vuelve a borrador. Una abierta cuya fecha de validez ya pasó se ve «Vencida» sin que nada corra en segundo plano.
8. «Crear versión nueva» de una enviada: mismo número, versión + 1, en borrador; la versión anterior queda intacta y aparece en «Versiones».
9. «Crear proforma» solo aparece con la cotización enviada, negociada o aprobada; abre el PDF de la proforma y queda con su propio número.
10. Abrir la misma cotización en dos pestañas, guardar en una y luego en la otra: la segunda avisa que fue modificada (no pisa).
11. El historial de la cotización no muestra el texto de las notas de la reunión, solo que cambiaron.
12. Salir de la página con cambios sin guardar pide confirmación del navegador.
13. `/crm/buscar`: buscar un nombre de 2 o más letras muestra cuentas, contactos, oportunidades, cotizaciones y leads (máx. 8 por grupo); sin tildes también encuentra. Una sola letra se rechaza con mensaje.
14. En la lista de cotizaciones: guardar un filtro por etapa, elegirlo después en «Filtros guardados». El texto de búsqueda NO se guarda.
15. «Exportar CSV» (solo admin): descarga cotizaciones con `;` como separador, tilde bien en Excel; una celda que empieza por `=` sale neutralizada. Un comercial no ve el botón y la API le responde 403.
16. Suprimir un contacto (Ley 1581): la vista previa cuenta las cotizaciones vinculadas, se desvinculan y sus PDF se borran. Suprimir una cuenta borra cotizaciones, proformas, PDF e historial.
17. Un usuario «coordinador» no ve ni la API ni las pantallas.
18. Revisar en 1000/1100/1280/1500 y 390 px, claro y oscuro: sin desbordes, objetivos ≥ 44 px.

## DECISIÓN (valores por defecto tomados)
- La exportación CSV es solo de admin, máximo 20 000 filas, con registro en auditoría (solo el número de filas).
- Importar CSV propio no se construye: la carga masiva es el importador de SuiteCRM (con sus tres candados).
- No hay `.docx`: el PDF es sencillo (texto y tablas), sin logo; encabezado, saludo y pie salen de la plantilla.
- Una cotización «vence» por cálculo al mostrarla, no por un proceso programado.
- La proforma se emite solo desde una cotización enviada, negociada o aprobada, y copia el total de ese momento.
- Productos, condiciones y plantillas solo las edita un admin; los comerciales las usan.
- El número de cotización es el mismo en todas sus versiones; el de proforma tiene contador propio.
- Los filtros guardados guardan solo campos estructurados (etapa), nunca texto libre.
- Consultas por pantalla: lista = 1 consulta + catálogo de etapas; editor = detalle + metadatos + contactos de la cuenta; búsqueda = 5 consultas con LIMIT 8, solo al pulsar «Buscar».

## Revisión visual (12-nov-2026, arnés con datos ficticios)
Lista, editor (borrador, enviada, con 40 líneas, textos larguísimos), productos y búsqueda a 1000/1100/1280/1500 y 390 px, claro y oscuro. Corregido: el botón «Quitar» partía la palabra en dos líneas, la columna del concepto era muy angosta, la etapa «Vencida» salía duplicada y las celdas de acciones mostraban un «—» sobrante.
Pendiente a mano en staging: abrir el PDF real en un lector y revisar la ortografía de las tildes.
