# Pendientes visuales (entrada de la Fase 2)

Lo que se ve feo o inconsistente fuera del alcance de la pieza en curso. Una línea por hallazgo: pantalla · qué falla · captura si hay.

| Pantalla | Qué falla | Visto en |
|---|---|---|
| Registro (`kiosk_registro.html`) | La página sigue en estilo antiguo (fondo blanco, estilos en línea, botones `golden-btn`) y no incluye `_gw_head.html`, así que **no tiene tema oscuro**. Solo el buscador único usa los estándares; el tema oscuro de toda la pantalla corresponde a la oleada del digitador de la Fase 2. | 1A · buscador único |
| Registro | La tabla del directorio, los botones de QR/cédula nueva y la barra de impresión usan colores y tamaños sueltos. | 1A · buscador único |
| Parámetros del evento (`kiosk_parametros.html`) | Plan 6 la agrupó y le dio el Guardar global con componentes `.gw-*`, pero el CONTENIDO de cada tarjeta sigue con estilos en línea (bordes `#ccc`, botones `golden-btn`/`small-btn`, tablas `.params-table`, tamaños sueltos de letra y casillas) y la página no incluye `_gw_head.html`: **sin tema oscuro**. Falta pasar campos y botones a `.gw-field/.gw-input/.gw-btn` y adoptar la base en la página. | Plan 6 · Parámetros agrupado |
| Parámetros del evento | La tabla de «Puestos de impresión» y la de «Impresión compartida» usan `<details>`/tablas con colores sueltos (`#e1e4ec`, `#1e7e34`, `#a12631`); la tabla de campos es ancha y en celular depende del desplazamiento horizontal. | Plan 6 · Parámetros agrupado |
