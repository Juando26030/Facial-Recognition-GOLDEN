# Impresión: parámetros confirmados en hardware (INAMOVIBLES)

Definidos y probados el **28-oct-2026** por Juan David con una Brother QL-800 en Windows 11 + Chrome (etiquetas de calibración y escarapelas ficticias, vertical y horizontal).
**Cualquier cambio que pueda afectar la impresión (compartir impresora, diseñador de escarapela, Parámetros, ventana de impresión, USB) se hace RESPETANDO esto.** Para cambiarlo hace falta que Juan David lo pida expresamente y se repita la prueba física.

## Ventana de impresión normal (`templates/badge_print.html`)
| Parámetro | Valor | Por qué (medido en la impresora) |
|---|---|---|
| Ancho de página `PAGE_W` | **62 mm** | Con 58,93 mm Chrome ignora `margin: 0` y vuelven fecha, ruta, título y «1/1». |
| Alto mínimo `PAGE_MIN_H` | **99,8 mm** (papel «62×99,8» del controlador); si la etiqueta es más alta, su altura exacta | 40, 45 y 65 mm traen los textos de Chrome; 60,6 mm lo gira el controlador (papel de 79 mm); 95, 99,8 y 110 mm salen limpias. |
| `@page` | `size: 62mm {alto}mm; margin: 0` | Sin márgenes ni escalado. |
| Margen izquierdo `PAGE_LEFT_MM` | **0,5 mm** | Etiqueta de 58,93 mm dentro del área imprimible (~60 mm desde el borde izquierdo). |
| Marca de fin `#endMark` | **0,3 mm × 0,3 mm negro, `position:relative; z-index:1`, en la última fila de la imagen** | El controlador recorta el blanco del final de la tira; sin la marca la horizontal salía de 6 cm en vez de ~9 cm. Sin `z-index` la imagen blanca la tapa y no sirve. |
| Imagen | La MISMA etiqueta compuesta que el USB (`static/js/label-compose.js`: recorte, giro, margen de Parámetros y ⚙️), 58,93 mm de ancho (696 puntos a 300 dpi) | Vertical y horizontal salen centradas, completas y sin textos de Chrome. |

## USB directo (WebUSB, `static/js/ql-usb.js`)
- Formato del trabajo y composición del bitmap **no se tocan** (`ql-usb.js`, `label-compose.js`).
- En Windows el controlador de Brother da «Access denied»: aviso claro, barra amarilla, sin botón «Conectar», sin reintentos en bucle, y ese equipo no se anuncia como dueño de la impresora.

## Impresión compartida
- Con compartida APAGADA: USB directo si hay impresora; si no, la ventana normal (misma etiqueta). Ninguna ruta compartida se llama.
- Dinámica del reclamo (lease de 60 s, Cola, «Imprimir pendientes») no se toca.

## Qué debe cumplir cualquier cambio futuro
1. La ventana normal y el USB imprimen **la misma etiqueta compuesta** (recorte, giro y margen iguales).
2. Nunca más textos de Chrome (fecha, ruta, título, «1/1») en la ventana normal: página de 62 mm y alto ≥ 99,8 mm.
3. Vertical y horizontal (plantilla 62×100 / 100×62 mm, con y sin recorte) siguen saliendo centradas y completas.
4. Si se toca el diseñador de escarapela, la composición o la ventana de impresión: repetir la prueba física (vertical y horizontal) y la de Chrome real; `tests/test_impresion_parametros_fijos.py` y `tests/js/label_compose_check.js` deben seguir verdes.
