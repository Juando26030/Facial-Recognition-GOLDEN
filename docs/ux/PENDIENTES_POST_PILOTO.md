# Pendientes de terceros en las páginas (después del piloto del 29 de octubre)

Decisión del dueño (17 oct 2026): estos scripts se siguen cargando desde `cdnjs.cloudflare.com`. Son pantallas del personal, no de los asistentes, así que no se alojan antes del piloto.

| Script | Pantallas |
|---|---|
| JsBarcode 3.12.3 | editor de escarapelas, impresión, escarapela digital, certificados (personal y público) |
| html2canvas 1.4.1, jsPDF 2.5.1 | certificados (personal y público) |
| JSZip 3.10.1 | certificados, carga de lista (roster) |
| Chart.js 4.5.1 | estadísticas, editor de formulario |
| SheetJS (xlsx) 0.18.5 | carga de lista (roster) |

Ya alojado: `qrcode-generator` 1.4.4 (`static/vendor/`). Cuando se alojen los demás, se hace igual: archivo en `static/vendor/` con su licencia y una prueba que falle si reaparece el dominio.
