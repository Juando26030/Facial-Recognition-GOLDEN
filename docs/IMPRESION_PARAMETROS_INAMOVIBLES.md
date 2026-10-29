# Impresión: parámetros confirmados en hardware (INAMOVIBLES)

Definidos y probados el **28-oct-2026** por Juan David con una Brother QL-800 en Windows 11 + Chrome (etiquetas de calibración y escarapelas ficticias, vertical y horizontal).
**Cualquier cambio que pueda afectar la impresión (compartir impresora, diseñador de escarapela, Parámetros, ventana de impresión, USB) se hace RESPETANDO esto.** Para cambiarlo hace falta que Juan David lo pida expresamente y se repita la prueba física.

## Ventana de impresión normal (`templates/badge_print.html`)
| Parámetro | Valor | Por qué (medido en la impresora) |
|---|---|---|
| Ancho de página `PAGE_W` | **62 mm** | Con 58,93 mm Chrome ignora `margin: 0` y vuelven fecha, ruta, título y «1/1». |
| Alto máximo de la imagen `MAX_IMG_H` | **96 mm** (si es más alta, se reduce proporcionalmente y queda centrada a lo ancho) | La impresora no imprime los últimos milímetros del papel: la marca de fin se pierde y el controlador acorta la tira. Probado el 28-oct-2026: imagen de 99,4 mm → tira de 6,2 cm y tinta pegada a un extremo; imagen de 96 mm → tira de 9 cm y centrada. Las plantillas de 100 mm (imagen de 95,08 mm) no cambian. |
| Alto `PAGE_H` | **SIEMPRE 99,8 mm** (el papel «62×99,8» del controlador). Una etiqueta más alta se reduce proporcionalmente para caber (centrada a lo ancho); una más baja conserva su tamaño real | Solo el papel EXACTO del controlador sale bien: 40, 45 y 65 mm traen los textos de Chrome; 60,6 mm lo gira el controlador (papel de 79 mm); **99,99 mm (apenas más que el papel) sale de 62×62 mm y con la tinta pegada a un extremo** (28-oct-2026, etiqueta horizontal de 105 mm en staging). Corrección del 28-oct: antes decía «si es más alta, su altura exacta». |
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

## USB (celular) — mismo largo máximo (29-oct-2026)
El camino USB aplica el MISMO largo máximo de 96 mm que la ventana de Chrome (`LabelCompose.fitToPaper`, constante `MAX_IMG_MM` = `MAX_IMG_H`); `tests/js/label_paths_check.js` lo vigila. Las etiquetas de hasta 96 mm (las de 100 mm de plantilla miden 95,08) no cambian en ningún camino.

## Qué debe cumplir cualquier cambio futuro
1. La ventana normal y el USB imprimen **la misma etiqueta compuesta** (recorte, giro y margen iguales).
2. Nunca más textos de Chrome (fecha, ruta, título, «1/1») en la ventana normal: página SIEMPRE de 62 × 99,8 mm.
3. Vertical y horizontal (plantilla 62×100 / 100×62 mm, con y sin recorte) siguen saliendo centradas y completas.
4. Si se toca el diseñador de escarapela, la composición o la ventana de impresión: repetir la prueba física (vertical y horizontal) y la de Chrome real; `tests/test_impresion_parametros_fijos.py` y `tests/js/label_compose_check.js` deben seguir verdes.
5. **Chrome SIEMPRE normal, con su cuadro de impresión visible: nunca `--kiosk-printing`** (orden de Juan David, 28-oct-2026). Ni lanzadores, ni scripts de arranque, ni perfiles aparte que impriman sin mostrar el cuadro: con él no se pueden ver ni cambiar el papel, la escala y los márgenes. Si algún equipo lo trae (proceso `chrome.exe --kiosk-printing`, p. ej. `Imprimir-GoldenWeb.bat`), se cierra y se abre Chrome normal.
