# QR dinámico y tarjeta en Wallet (Fase 8, pieza 4)

## Qué es, en simple
- **QR dinámico:** en la página personal de la credencial digital (`/b/<enlace>`), el QR cambia solo cada 30 segundos. Una captura de pantalla deja de servir en ~60-90 segundos. El código **no lleva la cédula**: lleva un número interno de la persona y una firma que solo nuestro servidor puede comprobar.
- **Tarjeta en Wallet:** botones «Agregar a Google Wallet» y «Agregar a Apple Wallet» en esa misma página. Solo aparecen cuando hay credenciales configuradas.

## Cómo funciona
1. La página pide al servidor `GET /b/<enlace>/qr` un lote de 4 códigos (2 minutos) y los va rotando; vuelve a pedir antes de que se acaben.
2. Al escanear en la puerta / áreas / inventario, la pantalla del operador (`static/js/qr.js`) detecta el código dinámico y lo valida en el servidor (`POST /api/qr/resolve`, requiere sesión de personal). El servidor responde con cédula y nombre, y el resto del flujo (registro, áreas, inventario) sigue igual que con el QR de la escarapela impresa. **El QR de la escarapela impresa no cambia.**
3. Códigos: `gwq1.<id>.<ventana>.<firma>` (dinámico) y `gwq1s.<id>.<firma>` (estático, solo para Wallet y **solo en la entrada**: `POST /api/qr/resolve` lo rechaza con `purpose` «area» o «inventory», que mandan áreas e inventario). Firma HMAC-SHA256 con una clave derivada de la configuración del servidor y del enlace secreto de la persona.
4. Errores: 400 código no válido o de otro evento; 410 vencido (captura vieja); 404 la persona ya no está.

## Limitación importante de Wallet
Un pase de Wallet es una tarjeta guardada en el teléfono: **no puede rotar** el QR cada 30 s sin notificaciones push de Apple/Google. Por eso el pase lleva el código **estático firmado** (válido, pero no caduca). Para ver el QR que rota, la persona abre su página. Esto es una decisión consciente; si el evento exige máxima seguridad, se pide el QR de la página.

## Revocar
- Regenerar el enlace digital de una persona (cambia su `digital_token`) invalida **todos** sus códigos, dinámicos y de Wallet.
- Archivar/finalizar el evento deja de dar códigos válidos para ese evento.

## Lo que necesita Juan David (solo si quiere Wallet)
**Google Wallet** (gratis): 1) cuenta de Google Wallet Business (Issuer ID) en pay.google.com/business/console; 2) un proyecto de Google Cloud con la API de Google Wallet activada y una cuenta de servicio con su llave JSON, dada de alta como usuario en la consola de Wallet; 3) en modo prueba solo se ven los pases de cuentas de prueba; para público general se pide aprobar la «publicación» en la consola.
**Apple Wallet** (USD 99/año, Apple Developer Program): 1) crear un *Pass Type ID* y su certificado; 2) exportar certificado y llave en PEM; 3) descargar el certificado intermedio WWDR de Apple en PEM.

Los secretos van a Secret Manager (nunca al chat ni al repo; los crea Juan David).

### Variables de entorno
- Google: `WALLET_GOOGLE_ISSUER_ID`, `WALLET_GOOGLE_SA_JSON`.
- Apple: `WALLET_APPLE_PASS_TYPE_ID`, `WALLET_APPLE_TEAM_ID`, `WALLET_APPLE_CERT_PEM`, `WALLET_APPLE_KEY_PEM`, `WALLET_APPLE_WWDR_PEM`, opcional `WALLET_APPLE_KEY_PASSWORD`. Los PEM pueden llevar `\n` literales.
- Sin estas variables no se muestra ningún botón y los endpoints de Wallet responden 404. El QR dinámico funciona sin ellas.

## Sin migración
No cambia la base de datos.

## Pruebas
`tests/test_qr_dinamico.py` (firma/ventanas, endpoints, JS y Wallet con certificados de prueba). Se corren en Cloud Shell con todo el conjunto.
