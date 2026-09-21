# Investigaciones de la reunión (2026-09-21) — ítems 12 y 13

Investigación de mercado hecha por búsqueda web el 2026-09-21. **Nada de esto está probado con hardware
real**: los datos salen de fichas de fabricantes y tiendas (fuentes al final). Antes de comprar, pedir una
unidad de prueba y probarla con una cédula nueva real.

## Ítem 12 — ¿Un mismo aparato para código de barras (cédula vieja) + MRZ (cédula nueva)?

**Respuesta corta: sí existen, y son los que hay que mirar.** Hay tres familias:

| Familia | Ejemplos encontrados | Qué lee | Notas |
|---|---|---|---|
| Lector de mano "pasaporte/ID" con OCR-B | RTscan **IDE302 / IDE303** (sensor CMOS 1280×800 / 1280×1024, USB) | MRZ (OCR-B) de pasaportes y cédulas TD1 **+** 1D y PDF417/QR | Un solo aparato para los dos flujos. Se conecta por USB. |
| Móvil/PDA Android con motor Honeywell y OCR | MUNBYN con Honeywell N6703 (1D/2D + OCR) | Códigos 1D/2D y OCR de documentos | Trae cámara y pantalla; sirve también para el flujo por foto. Más caro y más "computador" que lector. |
| Módulos fijos/kiosco con MRZ | Posunitech/EFFON **MS430** (PDF417, DataMatrix, OCR-B; USB/RS232) | Igual que arriba, montado fijo | Para una mesa de acreditación fija, no para caminar con él. |

- La cédula vieja colombiana trae **PDF417**: cualquier lector 2D estándar lo lee (referencias en Colombia:
  Zebra DS2208 ≈ COP 432.000, AON FS-205 ≈ COP 309.000, StarPos ≈ COP 214.700, Netum L5; Honeywell Xenon 1900
  es el clásico). Ese caso **ya funciona hoy** con el lector como "teclado" (ver `directory.js: parseOldCedulaBarcode`).
- La cédula nueva trae la **zona MRZ** (TD1, 3 líneas × 30 caracteres, OCR-B) en el reverso: la leen los
  lectores tipo RTscan IDE30x/MS430. Su QR está encriptado por la Registraduría y no se usa.
- **Cómo se integraría con este sistema:** estos lectores suelen entregar el texto de las 3 líneas MRZ como si
  fuera teclado (modo HID). Hoy el flujo de cédula nueva es "foto → OCR (Tesseract) → parser". El parser
  (`app/mrz_parser.py: parse_mrz_td1`) trabaja sobre **texto**, así que con un lector así se puede saltar el
  OCR: bastaría un campo que reciba las 3 líneas y llame al mismo parser (mejor precisión que el OCR de una
  foto de celular, y sin instalar Tesseract). Es un cambio chico, **no hecho** (era solo investigación).
- **Pendiente antes de comprar:** confirmar con el proveedor (a) que el modelo lee el MRZ de la **cédula
  colombiana nueva** (formato TD1; el parser se validó con una sola muestra real), (b) el modo de salida
  (teclado/USB-HID) y (c) disponibilidad y garantía en Colombia.

## Ítem 13 — Impresoras térmicas a color

**Aclaración importante:** casi no existe "térmica directa a color" para escarapelas. Lo que hay:

| Opción | Modelos | Cómo imprime | Pros | Contras |
|---|---|---|---|---|
| **Térmica 2 colores (negro+rojo)** | Brother **QL-800 / QL-810W / QL-820NWB** con rollo DK-22251 (62 mm) | Térmica directa | Es la línea que ya se usa (QL-800, 62×100 mm); rápida (~4 s por escarapela), barata (rollos ≈ USD 0,05–0,10 por escarapela), Wi-Fi/Ethernet/Bluetooth en la 820NWB | Solo negro y rojo, sin fotos a color |
| **Inyección de tinta a color para etiquetas** | Epson **ColorWorks CW-C4000** (ancho 4", hasta 1200 dpi, reemplazo de la C3500 descontinuada; ~USD 2.500), Primera **LX610e** (hasta 5" de ancho, corta sola) | Tinta CMYK (no térmica) | Color real con foto y logo; etiquetas resistentes al agua (C4000) | Ancho mínimo mayor que 62 mm (desperdicio si la escarapela es angosta), más costosas, tintas |
| **Tarjetas PVC a color** | Zebra **ZC300** (~200 tarjetas/hora) | Sublimación/retransferencia | Credencial durable para eventos de varios días | Lenta (≈ 18 s por tarjeta): se imprime por adelantado, no en la fila de acreditación |
| Etiquetas industriales a color | Afinia **L301 / L502 / L801** | Tinta | Volumen alto, dos tipos de tinta | Sobredimensionadas para un evento |

- **Recomendación para este sistema:** si basta con *un poco de color* (logo y texto en rojo), quedarse con la
  **Brother QL-820NWB + DK-22251** (misma familia que ya se usa). Si se necesita **foto y logos a todo color en
  la fila**, la opción realista es **Epson ColorWorks CW-C4000** (o la Primera LX610e) con etiquetas más anchas,
  rediseñando la escarapela a ese ancho. Para escarapelas que se entregan de un día para otro, tarjetas con la ZC300.
- **Compatibilidad con la app:** la impresión sale por el navegador con el tamaño real de la plantilla
  (`@page size`, ver `badge_print.html`); funciona con cualquier impresora que tenga driver del sistema
  operativo, pero **hay que probar el margen/tamaño de cada modelo** — el editor ya permite cualquier ancho/alto en mm.
- **Pendiente:** definir presupuesto y volumen (escarapelas por hora en la fila) para escoger entre tinta y tarjeta.

## Fuentes
- RTscan IDE303 (lector de pasaporte/MRZ + PDF417): https://www.rtscan.net/Code-Readers/hand-held-passport-ocr-b-mrz-reader/
- RTscan IDE302: https://www.rtscan.net/Code-Readers/handheld-mrz-reader-rt302/
- Unisystem IDE303 / IDE302: https://unisystem.com/product/barcode-scanners/handheld/ide303-handheld-passport-ocr-b-mrz-reader , https://unisystem.com/product/barcode-scanners/handheld/ide302-ocr-b-mrz-pdf417-reader
- MUNBYN Android con Honeywell N6703 y OCR: https://www.amazon.com/MUNBYN-Honeywell-Wireless-Computer-Inventory/dp/B0CZDCV6PX
- EFFON MS430 (módulo OCR/MRZ): https://www.effon.com/ocr-barcode-reader/
- Lectores para cédula colombiana (PDF417) y precios: https://www.capitalcolombia.com/clases/colombia/bogota/hardware/lectores_de_codigos_de_barras_cc1c.php , https://www.rtscan.com/es/pdf417-leitor-aplicacion/pdf417-lector-dni-de-colombia/
- Elegir impresora de escarapelas 2026: https://www.engineerica.com/conferences-and-events/post/event-badge-printer/
- Epson ColorWorks CW-C4000: https://epson.com/For-Work/Printers/Label/ColorWorks-CW-C4000-Color-Inkjet-Label-Printer-(Gloss)/p/C31CK03A9991
- Comparación Epson ColorWorks: https://www.spectrafloweast.com/post/colorworks-comparison
- Brother QL-800/810W/820NWB: https://www.brother-usa.com/p/thermal-printers-labelers/QL820NWB , https://www.labelking.co.uk/news/choosing-the-right-brother-label-printer-ql-800-vs-ql-810w-vs-ql-820nwb.html
- Primera LX610: https://www.primera.com/lx610-color-printer-cutter-config.html
- Afinia: https://afinialabel.com/
