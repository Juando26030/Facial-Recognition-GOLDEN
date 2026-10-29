# GoldenWeb 2.0 — Novedades de la versión del 29 de octubre de 2026

Lo que **cambia para quien opera**. Todo lo demás (registro, contingencia sin conexión encendida, sesión única, impresión compartida) queda como en la versión anterior.

## Nuevo: exportar e importar eventos entre entornos (solo super_admin)
- **📦 Exportar** (en «Clientes», en cada evento, y en «Eventos»): arma un paquete `.zip` con **todo** el evento — configuración y parámetros, campos, plantilla de escarapela, formularios, ruleta, personas, registros con sus horas, consentimientos y los archivos (imágenes, firmas, documentos, comprobantes, logo e informe). El asistente muestra el avance y entrega un enlace de descarga que **dura 5 minutos**; el paquete se **borra solo del servidor a las 24 horas**.
- **📥 Importar evento** (en cada cliente, y uno general en «Eventos»): crea un evento **NUEVO** a partir de un paquete. **Nunca sobrescribe** un evento que ya existe. Primero hace un **simulacro** (no escribe nada) que muestra qué entraría y qué se omitiría; después importa de verdad y muestra el informe **«Origen vs Destino»**.
- **Cuidados que hace solo:** no envía correos, no toca Wompi y no crea pagos nuevos (los pagos entran como histórico). Las cuentas del personal **no se copian** (el nombre de quien registró queda como texto si esa cuenta no existe aquí). Las personas suprimidas no se vuelven a crear. Los formularios entran en «pruebas» y un evento «en proceso» queda **en espera** (estado «Creado») hasta que se **confirma**; solo al confirmar puede activarse el congelamiento de despliegues.
- **Biometría:** por defecto **no** se exporta. Con la opción «incluir biometría» (frase de transporte de 8+ caracteres que **no se guarda**) los rostros y fotos viajan cifrados y solo entran personas nuevas, **mayores de edad y con consentimiento aceptado**; el destino los vuelve a cifrar con su propia llave. Las fechas originales se conservan (la retención de 7 días / 180 días sigue contando con ellas).
- **El paquete lleva datos personales:** guárdalo con cuidado y bórralo de tu computador cuando termines.

## Impresión (Brother QL-800) — parámetros confirmados
- **La ventana de impresión sale limpia y centrada** en etiqueta vertical y horizontal, **sin** fecha, ruta, título ni «1/1» de Chrome. La página es siempre de **62 × 99,8 mm** y la imagen mide **como máximo 96 mm** (una plantilla horizontal más larga se reduce un poco para caber).
- **La horizontal con recorte sale centrada a lo largo de la tira** (antes quedaba pegada a un extremo).
- **Usa Chrome normal, con su cuadro de impresión visible.** No uses accesos directos ni archivos `.bat` que abran Chrome con `--kiosk-printing` (imprimen sin mostrar el cuadro y no se pueden cambiar papel, escala ni márgenes). Si un equipo los tiene, se cierran y se abre Chrome normal.
- Las etiquetas cortas siguen saliendo en papel de unos 10 cm (queda tira en blanco al final).

## Lo que NO cambia
- Textos de autorización y política de privacidad. No se recoge ningún dato personal nuevo.
- La **contingencia sin conexión sigue ENCENDIDA** en producción.
