# Pendientes visuales (entrada de la Fase 2)

Lo que se ve feo o inconsistente fuera del alcance de la pieza en curso. Una línea por hallazgo: pantalla · qué falla · captura si hay.

| Pantalla | Qué falla | Visto en |
|---|---|---|
| Parámetros del evento (`kiosk_parametros.html`) | Plan 6 la agrupó y le dio el Guardar global con componentes `.gw-*`, pero el CONTENIDO de cada tarjeta sigue con estilos en línea (bordes `#ccc`, botones `golden-btn`/`small-btn`, tablas `.params-table`, tamaños sueltos de letra y casillas) y la página no incluye `_gw_head.html`: **sin tema oscuro**. Falta pasar campos y botones a `.gw-field/.gw-input/.gw-btn` y adoptar la base en la página. | Plan 6 · Parámetros agrupado |
| Parámetros del evento | La tabla de «Puestos de impresión» y la de «Impresión compartida» usan `<details>`/tablas con colores sueltos (`#e1e4ec`, `#1e7e34`, `#a12631`); la tabla de campos es ancha y en celular depende del desplazamiento horizontal. | Plan 6 · Parámetros agrupado |
| Registro (`kiosk_registro.html`) | Plan 7 la pasó a la base nueva y al tema oscuro; quedan con estilos en línea heredados los modales internos (alta/edición, escáner, MRZ) y las filas/botones que arma `directory.js` (clase `golden-btn`, restilizados por `registro.css`). Revisar contraste en oscuro en staging. | Plan 7 · Registro limpio |
