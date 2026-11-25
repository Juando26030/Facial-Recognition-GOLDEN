# Banco de pruebas del escáner de cédula (sin celular)

Corre el código REAL del escáner (`static/js/cedula-foto.js` + `static/js/cedula-readers.js`) en Chrome sin pantalla, con una foto como cámara simulada.
Todo es sintético: la «cédula» la dibuja `gen.py` con datos inventados. No va en el CI (necesita Chrome, `tesseract`, OpenCV, Pillow y Playwright).

```bash
python tests/lab_cedula/gen.py                       # 16 casos con nombre + 60 al azar en /tmp/lab_cedula (LAB_OUT)
CONF=70 python tests/lab_cedula/srv.py &             # http://127.0.0.1:8765  (CONF=70: obliga a confirmar con 2 lecturas, como pasa en un celular)
python tests/lab_cedula/run.py /tmp/lab_cedula/img   # un renglón por foto: OK/FALLA, segundos y lecturas de OCR
python tests/lab_cedula/run.py /tmp/lab_cedula/rnd
python tests/lab_cedula/run.py /tmp/lab_cedula/img2  # torcida 45°/60°, brillo sobre las letras, sin cédula
KIND=old python tests/lab_cedula/run.py /tmp/lab_cedula/old   # cédula vieja: derecho, al revés, torcida, de lado
```

- **Comparar con otra versión:** `REPO=/ruta/a/otra/copia python tests/lab_cedula/srv.py` (esa carpeta debe tener `static/js/`).
- **Camino del servidor** (`/cedula-mrz-scan` con el preprocesado real de `app/mrz_ocr.py`): `curl "http://127.0.0.1:8765/mode?real,badocr"` y `EV=1 python tests/lab_cedula/run.py …`
  (`badocr` hace fallar el OCR del navegador para que decida el servidor).
- **Cédula vieja:** `KIND=old` usa un decodificador de REEMPLAZO (no hay zxing sin red) que solo «lee» el código de mentira de `gen.py` cuando le llega derecho y nítido:
  prueba ubicar, enderezar, girar y los tiempos; no la decodificación real del PDF417.

- **Decodificador REAL de la cédula vieja:** `ZX=real KIND=old EXPECT=<cédula esperada> python tests/lab_cedula/run.py <carpeta>` usa `zx.py` (zxing-cpp del sistema por GStreamer: `libgstzxing`).
  `CORES=4` simula la tableta modesta (vista previa 1080p; la foto fija sale a la resolución del archivo). `BUDGET=40000 WAIT=120` quita el límite de tiempo (para saber el techo) y
  `ZXDUMP=/carpeta` en `srv.py` guarda cada recorte que se intentó.
- **Cédulas reales:** las escenas se generan desde una imagen propia FUERA del repositorio (nunca se suben fotos ni datos reales). Ver docs/PRUEBA_LECTOR_CEDULA.md § Prueba con cédulas reales.

Límites: el OCR es el `tesseract` del sistema (no tesseract.js), la letra es Liberation Mono (no OCR-B) y no hay plástico, hologramas ni manos. Sirve para la GEOMETRÍA
(ubicar, enderezar, recortar, tiempos y flujo); la última palabra la tiene la prueba con cédulas reales.

Resultado del 24-nov-2026 (60 fotos al azar, solo navegador): versión anterior 27/60 · con recorte automático 58/60 (las 2 que fallan: letras de 15–19 px de alto y desenfocadas).
