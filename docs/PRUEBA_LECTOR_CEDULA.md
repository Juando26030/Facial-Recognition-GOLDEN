# Prueba: lector de cédula por cámara (PDF417)

**Ruta:** `/pruebas/lector-cedula` (por ejemplo `https://app.golden-eventos.com/pruebas/lector-cedula`). Requiere sesión del personal (digitador o más).

**Qué es:** la página de un solo archivo entregada el 19-nov-2026 (versión 3), servida **tal cual** desde `app/pruebas/lector_cedula.html`
(`tests/test_lector_cedula_prueba.py` fija su huella SHA-256). Lee el PDF417 del reverso de la cédula colombiana con la cámara en vivo o con una foto y
muestra `cédula,nombre1,nombre2,apellido1,apellido2,AAAAMMDD`. **Todo se procesa en el navegador: no llama a ninguna API de la app, no guarda nada y no toca la base de datos.**

**Dependencia externa:** descarga `zxing-wasm@3.1.3` desde `cdn.jsdelivr.net` (respaldo `unpkg.com`). La ruta fija su propia política CSP «Report-Only» que lo permite;
si más adelante se quiere sin CDN, copiar `zxing_reader.wasm` y el JS a `static/` y cambiar las URLs en el archivo (y actualizar la huella del test).

**Cómo probar:** abrir la ruta en el celular (HTTPS, cámara permitida: la app ya envía `Permissions-Policy: camera=(self)`) y usar «Abrir cámara» o «Tomar foto» con la cédula física.

**Datos personales:** la cédula es dato personal. Esta prueba no registra nada; no se debe conectar a registros de personas sin la autorización y el consentimiento que exige el proyecto.
**Para retirarla:** borrar la ruta en `app/main.py`, `app/pruebas/` y `tests/test_lector_cedula_prueba.py`.


## Pestaña «Cédula nueva» (las 3 líneas de abajo) — 19-nov-2026
La página tiene dos pestañas: **Cédula vieja** (código de barras PDF417, el lector de siempre, sin cambios) y **Cédula nueva**. La nueva no usa el QR (va cifrado):
lee con OCR las **3 líneas de letras, números y «<»** del reverso (zona legible por máquina, formato TD1 de la OACI) y devuelve el mismo formato
`cédula,nombre1,nombre2,apellido1,apellido2,AAAAMMDD` (además muestra sexo, vencimiento y n.º de documento).

- **No depende de posiciones fijas:** la cédula es lo que sigue a `COL` en la línea 2 hasta el siguiente `<`; los nombres se separan por `<<` (apellidos | nombres) y `<`.
  Las líneas pueden llegar en cualquier orden y la cédula puede tener 6–11 dígitos.
- **Confiabilidad:** los dígitos de control (7-3-1) validan nacimiento, vencimiento, n.º de documento y el control general (que cubre la cédula). Los nombres no tienen control:
  se aceptan al verlos **iguales en dos cuadros** (o con confianza alta en uno). Si los controles no cuadran, el resultado sale como «aproximado, verifica».
- **Cámara:** recuadro guía fijo (3 renglones de ayuda), endereza la inclinación, separa las 3 líneas, enfoca por nitidez relativa y lee en cuanto está enfocado. Si la cédula está al revés, prueba girada 180°.
  «Diagnóstico» muestra las 3 líneas como las ve el OCR y el texto leído. «Tomar foto»/«Galería» localizan las 3 líneas en cualquier parte y orientación de la foto.
- **Dependencia externa:** `tesseract.js@5.1.1` y el idioma `eng` (`@tesseract.js-data/eng`) desde `cdn.jsdelivr.net` (respaldo `unpkg.com`); se descargan la primera vez (~5–10 MB) y quedan en caché del navegador.
  Un trabajador de OCR por línea, cada uno con su lista de caracteres permitidos (línea 2 solo dígitos y `MFCOLX<`; línea 3 solo letras y `<`).
- **Pruebas:** `node tests/js/mrz_parser_check.js` (parser, datos sintéticos). El OCR en sí se valida con cédulas físicas en el celular (no hay datos reales en el repo).


## Quiosco: Registro → «Escanear» (cédula vieja · cédula nueva · QR) — 19-nov-2026
El botón **Escanear** (junto a «Registrar nuevo» en `/kiosk/<evento>/registro`) abre la MISMA ventana de cámara de siempre (`static/js/qr.js`, `QrScanner.open`), ahora con un selector
**Cédula vieja · Cédula nueva · QR** (`modes`). El diseño no cambia; se recuerda el último modo elegido (`localStorage`, clave `gw_scan_mode`; por defecto QR).

- **QR:** exactamente lo de antes (QR de escarapela/dinámico, y el PDF417 por `BarcodeDetector` si el navegador lo trae; el botón «Foto del reverso» sigue ahí, solo en este modo).
- **Cédula vieja / nueva:** al elegirlas se carga `static/js/cedula-readers.js` (los mismos lectores de la página de prueba) con recuadro guía sobre el video. El resultado entra por el mismo camino que el PDF417 de siempre:
  `directorySearch.submitScannedCedula(cédula, {nombres, apellidos})`. La misma cédula quieta frente a la cámara no se envía dos veces (4 s) y tras cada lectura sigue con la siguiente persona.
  **Cédula nueva solo entrega lecturas VERIFICADAS** (dígitos de control en regla, incluido el general que cubre la cédula, y nombres confirmados): para acreditar a alguien no se acepta una lectura «aproximada».
- **Fuente única:** `static/js/cedula-readers.js` está GENERADO desde `app/pruebas/lector_cedula.html` (`python scripts/build_cedula_readers.py`); `tests/js/mrz_parser_check.js` falla si quedó desactualizado.
  Cualquier ajuste al lector se hace en la página de prueba y se regenera.
- **Sin CDN / sin internet (pendiente):** hoy zxing-wasm, tesseract.js y el idioma se bajan del CDN la primera vez (y quedan en caché del navegador). `scripts/vendor_cedula_readers.sh` (correr una vez con internet) deja
  una copia propia en `static/vendor/cedula/` que los lectores usan primero. **Ese script no se ha ejecutado** (el entorno de desarrollo no tiene red). Sin esa copia, el modo cédula necesita internet la primera vez en cada dispositivo;
  el modo QR sigue funcionando sin red como siempre.
- **CSP:** la política «Report-Only» del panel ahora lista `cdn.jsdelivr.net`/`unpkg.com` (script/connect) y `'wasm-unsafe-eval'`; no bloquea nada.


## Cédula por FOTO con guía (en vez de leer en vivo) — 24-nov-2026
Pedido de Juan David: leer la cédula cuadro a cuadro a veces tardaba o fallaba. Ahora, en el modo **Cédula vieja** o **Cédula nueva** de la ventana «Escanear» (Registro, alta manual,
Control de Áreas y Control de Inventario; todas usan `QrScanner.open` de `static/js/qr.js`), la cámara muestra el MISMO recuadro guía y un botón **«Tomar foto»**. **El QR no cambia: sigue en vivo.**

- **Componente único:** `static/js/cedula-foto.js` (`CedulaFoto.attach`), lo carga `qr.js` bajo demanda (y el service worker del quiosco lo guarda, `QrScanner.FOTO_URL`).
- **Foto:** `ImageCapture.takePhoto()` a la resolución máxima del sensor (Chrome/Edge en Android y computador); si no existe (iOS Safari, Firefox) o falla, el cuadro del video a resolución completa
  (el video se pide a 4K → 1440p → 1080p → lo que dé la cámara). Mientras se procesa, la imagen queda congelada y sale «Procesando la foto…».
- **Cédula vieja (PDF417):** recorte del recuadro (con margen) y, si no, la foto completa, con `CedulaScanner.scanImage` (plan «deep»: contraste, binarizado, enfoque, enderezado, giros, 180°, escalas).
- **Cédula nueva (3 líneas):** recorte ajustado, recorte holgado y la foto completa (`MrzScanner`); cada recorte con 3 tamaños de letra y, si hace falta, girado 180°. La cédula sale siempre validada
  por los dígitos de control; los nombres solo si dos lecturas coinciden o la confianza es alta (si no, se entrega la cédula sin nombres y el flujo sigue por cédula).
  **Respaldo:** si el navegador no la lee (o no pudo cargar el OCR) y hay red, la foto reducida (≤ 2400 px) va a `POST /api/events/<id>/cedula-mrz-scan` (Tesseract del servidor, solo responde con dígitos de control en regla).
  En modo sin conexión no se envía nada.
- **Datos personales:** la foto no se guarda en el navegador ni en el servidor y no se escribe en registros; se descarta en memoria al terminar. La cámara se libera al cerrar la ventana o cambiar de modo.
- **Falla:** «No se pudo leer la cédula: acérquela, evite reflejos y tome otra foto.» (la cámara sigue abierta para otra foto).
- **Pruebas:** `node tests/js/cedula_foto_check.js` (lógica pura) y `tests/test_cedula_camara_busqueda.py`. La lectura real se valida con cédulas físicas en el celular y el computador.
- La página de prueba `/pruebas/lector-cedula` y `cedula-readers.js` NO cambiaron (su huella sigue igual).

### Ajuste del 24-nov-2026 (tarde): una sola pantalla y más rápido
- **Pantalla:** en modo cédula, en celular y tableta la ventana ocupa el alto visible y la cámara llena el espacio libre; «Tomar foto» va encima de la parte baja del video (el recuadro guía queda centrado y no se tapa). En computador el botón también va encima del video.
- **Rapidez:** si el video ya es HD (lado corto ≥ 1080 px) se usa su cuadro en vez de `takePhoto()` (en Android tardaba 1-3 s). Cédula vieja: 2,5 s sobre el recuadro y 3 s sobre la foto completa (antes 7 s + 9 s). Cédula nueva: si el navegador no la leyó en 1,2 s, el servidor arranca en paralelo y gana el primero que la valide; con servidor disponible el navegador ya no hace el OCR lento de la foto completa. Sin conexión: solo el navegador, como antes.

### Reflejos e iluminación (24-nov-2026, prioridad de Juan David)
Regla de oro: **«Está» y «No está» solo salen de una lectura VALIDADA** (dígitos de control de la cédula nueva; corrección de errores del código de barras de la vieja) **con coincidencia exacta** en la base. Ninguna otra cosa acredita.
- **Ráfaga:** cada «Tomar foto» toma 3 cuadros seguidos (≈0,25 s). La vieja prueba el recuadro de cada uno (2 + 1 + 1 s) y luego la foto completa (2 s); la nueva junta las lecturas de los tres para votar letra por letra (dos lecturas iguales de cuadros distintos confirman los nombres).
- **Brillo en vivo:** cada 0,5 s se mira el recuadro; si más del 1,2 % está quemado (blanco en los tres colores), el recuadro se pone ámbar y sale «Hay un brillo sobre la cédula: inclínela un poco…». Si la lectura falla con brillo, el mensaje lo dice.
- **Linterna:** botón arriba a la derecha solo si el celular la ofrece (Android Chrome). En cédulas plastificadas a veces causa el brillo: el aviso pide apagarla.
- **Lectura a medias (cédula nueva):** si nada quedó validado pero se leyó parte del número o del nombre, `POST /api/events/{id}/cedula-near` (app/cedula_near.py) busca cédulas a UN error de lectura (un dígito cambiado, de más, de menos o dos vecinos intercambiados) y nombres parecidos (app/name_index.py), y la ventana pregunta «No se leyó completa. ¿Es alguna de estas personas?». El operador elige y la persona entra por el camino exacto de siempre; nada se acredita solo. La cédula vieja no tiene lectura parcial posible (su código o se recupera entero o no sale): ahí ayudan la ráfaga, el aviso de brillo y la linterna.

## Recorte automático «como CamScanner» (24-nov-2026, tarde)

Pedido de Juan David: que la foto funcione aunque la cédula no quede exactamente en el recuadro. El recuadro pasa a ser una ayuda, no un requisito.

- **Cédula nueva:** `CedulaReaders.mrzFind` (fuente: `app/pruebas/lector_cedula.html`) busca las 3 líneas en TODA la foto. Cada línea se reconoce como un bloque alargado y se mide con
  sus ejes principales (centro, ángulo, largo y grosor); se aceptan 3 bloques paralelos, del mismo largo, alineados y a la misma distancia. Entrega SOLO esa zona, enderezada, a la
  resolución de la foto y con la posición exacta de cada línea (el OCR ya no las vuelve a buscar: eso era lo que fallaba con el borde de la cédula o el fondo). Tolera la cédula
  pequeña (desde ~1/7 del ancho de la foto), corrida, girada hasta ~±25°, de lado o al revés. Después se limpia el fondo de cada línea (alto contraste) y se lee como siempre.
- **Servidor:** cuando el navegador ya ubicó las 3 líneas, a `/cedula-mrz-scan` va solo ese recorte (más liviano y sin el resto de la cédula).
- **Cédula vieja:** tras el recuadro de la primera foto se pasa la foto COMPLETA de cada cuadro de la ráfaga; `CedulaScanner.scanImage` ubica el código por textura, lo endereza y lo recorta.
- **Segundo intento con más detalle:** si la cédula se vio (líneas o código ubicados) pero no se pudo leer en el cuadro del video, se toma una foto fija a la resolución máxima del sensor y se repite.
- **Regla de oro intacta:** solo se entrega una lectura validada (dígitos de control en la nueva, corrección de errores en la vieja).
- **Por qué falló el intento anterior (242fa6bd):** usaba el localizador viejo (`mrzLocate`), que encontraba la zona pero luego volvía a buscar las líneas dentro del recorte y se
  confundía con el borde de la cédula. Se comprobó en el banco de pruebas.
- **Banco de pruebas:** `tests/lab_cedula/` corre el escáner real en Chrome sin pantalla con cámara simulada (fotos sintéticas). 60 fotos al azar, solo navegador: antes 27/60, ahora 58/60;
  16 casos con nombre: 15/16 (el que falla tiene las 3 líneas fuera de la foto). Camino del servidor con recorte: 9/9. Prueba automática del localizador: `tests/js/mrz_find_check.js`.
- **Falta:** probar con cédulas reales y celular (plástico, hologramas, letra OCR-B). La cédula vieja no se pudo leer en el banco (no hay zxing sin red): solo se verificó que el flujo corre sin errores.

## Al revés, torcida y chequeo previo (24-nov-2026, noche)

Pedido de Juan David tras probar el recorte automático en el celular: la cédula vieja al revés no leía, y con brillo o torcida se quedaba pensando ~15 s antes de decir que no.

- **Cédula vieja al revés:** `PLANS.photo` alterna derecho / girado 180° desde el primer intento (en `deep` los giros llegaban tras ~27 decodificaciones y el tiempo no alcanzaba).
  `scanImage(file, { plan: 'photo', cropsOnly })`. Torcida ya la cubría el localizador (rectángulo orientado).
- **Cédula nueva torcida:** si no se ubican las 3 líneas, se repite la búsqueda sobre la foto girada 45°: entre las dos se cubre cualquier ángulo. Se LEE, no se rechaza.
- **Chequeo previo (`washedCells`)**: las zonas donde debe haber tinta en todo el ancho (las 3 líneas; el código) se parten en celdas; una celda con < 40 % del contraste típico está
  «lavada». Más claras que lo normal = brillo; si no, sombra u objeto. Cédula nueva: ≥ 3 celdas lavadas → se avisa SIN procesar; 1–2 → se intenta el primer cuadro y, si no sale, se avisa.
  Cédula vieja: tras el primer cuadro, ≥ 4 de 48 → se avisa. Sin líneas / sin código a la vista → se avisa de una vez (ya no se manda la foto completa al servidor, que tardaba en decir que no).
- **Topes de tiempo:** cédula nueva 5,5 s por foto (navegador y servidor); cédula vieja ≈ 4,6 s. La foto fija «con más detalle» solo cuando la cédula se vio, sin brillo, pero lejos.
- **Mensajes con motivo:** brillo, algo la tapa, no se ven las líneas / el código, quedó muy lejos.
- **Banco (`tests/lab_cedula`, carpetas `img2/` y `old/`):** nueva a 45°, 60°, −40° y 135°: 4/4; brillo sobre las letras: aviso en 0,6 s; sin cédula: aviso en ~1 s. Vieja (con un decodificador
  de reemplazo que solo «lee» el código derecho): derecho, al revés, pequeña al revés, torcida, torcida al revés y de lado: 8/8; sin cédula: aviso en 1,4 s.
  El chequeo de brillo de la cédula vieja solo quedó probado como función (`tests/js/cedula_foto_check.js`), no en el banco.

## Vista previa fluida en equipos modestos (24-nov-2026, noche)

Juan David probó con una tableta que no es de última generación: al abrir la cámara del escáner la imagen iba trabada y con retraso, y costaba encuadrar. La lectura no cambió; solo se aligeró la vista previa.

- **Resolución del video:** mostrar 4K en vivo era lo más pesado. Equipo modesto (≤ 4 núcleos o ≤ 3 GB, `lowEnd`): se pide 1080p de entrada. En los demás se MIDEN los cuadros por segundo
  de la vista previa (`requestVideoFrameCallback`, 1,2 s) y, si van a menos de 18, se baja a 1080p con `applyConstraints` (sin volver a pedir permiso); a 720p solo si sigue a menos de 12 y
  el navegador tiene foto fija (`takePhoto`), que es la que se usa por debajo de 1080p. Se conserva la forma y la orientación del video; si el cambio la altera, se deshace.
- **Guía:** el lienzo del recuadro ahora mide lo que mide en pantalla (antes, la resolución del video: un lienzo 4K encima del video).
- **Aviso de brillo:** el recorte y la reducción se hacen con `createImageBitmap` (ya no se trae a memoria el cuadro completo cada medio segundo) y no corre con la pestaña oculta.
- **Lectores:** el OCR y el lector de códigos se cargan DESPUÉS de abrir la cámara y medir, para que su arranque no compita con ella.
- No se pide `frameRate`: en la prueba cambiaba el formato que elegía la cámara.
- **Banco:** mismos resultados que antes (15/16, 58/60, vieja 8/9). El bajón de resolución se probó simulando 8 cuadros por segundo (4K → 1080p → 720p; vertical 1080×1920 → 720×1280).
- **Falta:** confirmarlo en la tableta real. Si sigue trabada a 1080p, anotar modelo y navegador.

## Prueba con cédulas reales y decodificador real (24-nov-2026, noche)

Juan David prueba mostrando la cédula en la pantalla de un celular en horizontal (así llega la gente que olvidó el documento) y con una tableta modesta. Reportó: cédula vieja 3 de 5,
al revés no leía, un «zoom» que no se quitaba y demora para decir que no. Entregó un PDF de una cédula vieja y la foto de una nueva; se usaron SOLO en carpeta temporal (no van al repo).

**Banco con decodificador real.** `tests/lab_cedula/zx.py` usa el zxing-cpp del sistema (por el complemento de GStreamer) en lugar de zxing-wasm: `ZX=real`. Las escenas se generan
desde la imagen real (celular con marco negro, trama de pantalla, desenfoque, giros, brillo) a 4K; con `CORES=4` el banco reproduce la tableta: vista previa 1080p y foto fija del sensor a 4K.

**Causas encontradas (cédula vieja):**
1. *Ángulo del recorte.* El localizador mide el giro por la forma de la mancha de textura y erraba 2–4° (más al revés, donde el texto vecino entra en la mancha). El decodificador
   de PDF417 no tolera 3°: el mismo recorte no se leía a 0° y sí corrigiéndolo. → `_refineAngle`: ángulo por las barras verticales (signo verificado) y, con el recorte ya derecho,
   límites del código por la densidad de bordes (antes a veces salía MEDIO código).
2. *Resolución.* A 1080p el código queda en ~2 px por módulo. → cuadro del video primero y, si falta detalle, foto fija del sensor (`stillHD`).
3. *Orden de intentos.* `PLANS.photo`: `raw`, `sharp`, `stretch`, derecho y al revés alternados (`sharp` es el que más rescata fotos de pantalla).

**El «zoom»:** se quitó el cambio de resolución con la cámara abierta (recorta la imagen en algunos equipos). Si la vista previa va lenta, la SIGUIENTE apertura pide 1080p.
Tras una foto fija se restauran zoom y resolución del video si el equipo los cambió.

**Avisos rápidos (cédula vieja):** sin código → ya; brillo que lo tapa → ya; menos de 1 px por módulo → «muy lejos»; borroso (nitidez `sharpOf` < 0,3 en video con detalle, < 0,6 en la foto fija) → ya.
**Cédula nueva:** derecho y al revés alternados desde el primer intento (al revés tardaba el triple).

**Resultados (decodificador real, tableta simulada):**
- Cédula nueva real, 44 posiciones (tamaños, 0–360°, suave): 42/44 (una es «sin cédula»; la otra, pequeña a ~200°). Lee en 1,6 s de media (máx. 2,3 s); dice que no en ~1,5 s.
- Cédula vieja real, 69 escenas: nítida 10/10 · girada limpia (6°–270°) 12/14 · foto de pantalla con trama 6/10 · muy borrosa 0/10 · girada con trama 0/9. Antes de estos cambios: 19 de 55.
  Lee en ~1,1 s de media; dice que no en ~1,9 s (más lo que tarde la foto fija del equipo, cuando hace falta).
- Lo que NO se lee es límite del decodificador con esa calidad de imagen (se comprobó sin límite de tiempo: 21/55 antes de los arreglos). Las escenas «con trama» y «borrosa» son
  simulaciones duras; no se sabe qué tan cerca están de la tableta real.
- **Falta:** la prueba en la tableta real. Los umbrales de nitidez y brillo están calibrados con simulación.

