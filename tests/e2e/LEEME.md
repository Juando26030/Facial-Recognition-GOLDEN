# Pruebas de extremo a extremo (E2E) contra STAGING

**Aviso honesto:** estas pruebas se escribieron sin poder correrlas contra staging (quien las preparó no tenía red hacia staging ni la aplicación). Se verificó que el código compila y que los nombres de pantallas y campos que buscan existen en las plantillas, pero **la primera corrida real la haces tú**. Es normal que alguna falle o se salte la primera vez por un nombre de botón o una función que staging aún no tiene: avísame y se ajusta.

## Qué son
Un robot abre un navegador de verdad (Chrome sin ventana), entra a **staging** con una cuenta de pruebas y hace lo que haría una persona: iniciar sesión, crear un evento inventado «E2E-fecha», registrar a alguien por cédula, revisar que la tabla de Registro se vea bien en celular y pantalla grande, probar que las confirmaciones escritas se pidan, etc. Al terminar borra o archiva lo que creó.

**Nunca corren contra producción:** si la dirección contiene `app.golden-eventos.com`, o no contiene `staging`/`localhost`/`127.0.0.1`, se niegan a correr.

## Cómo correrlas (un solo comando)
Necesitas Python y Playwright instalados una vez: `pip install pytest playwright` y `playwright install chromium`.

Cloud Shell o Linux/Mac (cambia lo que está entre `<...>`; las claves no se guardan en ningún archivo):

```bash
E2E_BASE_URL="https://<direccion-de-staging>" E2E_USER="<usuario-de-pruebas>" E2E_PASSWORD="<clave-de-pruebas>" python3 -m pytest -v tests/e2e
```

Windows (PowerShell), todo en una sola pegada:

```powershell
$env:E2E_BASE_URL="https://<direccion-de-staging>"; $env:E2E_USER="<usuario-de-pruebas>"; $env:E2E_PASSWORD="<clave-de-pruebas>"; python -m pytest -v tests/e2e
```

Opcionales (agrégalas igual): `E2E_DIGITADOR_USER` y `E2E_DIGITADOR_PASSWORD` (prueba del digitador), `E2E_URL_PUBLICO` y `E2E_URL_BIOMETRIA` (humo de los otros servicios), `E2E_TENANT_ID` (cliente donde crear el evento de prueba).

También se puede lanzar desde GitHub: Actions › «Pruebas E2E en staging» › Run workflow (usa los secretos `E2E_BASE_URL`, `E2E_USER`, `E2E_PASSWORD`; si falla, deja capturas y video como descarga).

## Qué significan los resultados
- **passed (verde):** esa comprobación salió bien.
- **failed (rojo):** algo no se comportó como se espera. El mensaje dice qué (por ejemplo «a 390px la página se desplaza 14px»). Es lo que hay que revisar.
- **skipped (saltada):** no se pudo probar y dice por qué (falta la cuenta, no hay llaves para probar, staging aún no tiene esa función, la impresión requiere impresora). No es un fallo, pero tampoco cuenta como aprobada.
- Sin `E2E_BASE_URL`, el resto de pruebas del proyecto (`pytest` normal) ignoran esta carpeta.

## Qué NO prueban
- No prueban producción, ni el sitio web público (es otro dominio), ni pagos, correos, SMS o WhatsApp.
- No prueban reconocimiento facial real ni la cámara.
- No prueban la impresión física de la escarapela (queda marcada como saltada; los parámetros 62 × 99,8 mm los protege `tests/test_impresion_parametros_fijos.py`).
- No reemplazan la revisión visual de una persona ni las pruebas de carga.
- Si la cuenta de pruebas no es super_admin, los eventos «E2E-...» quedan archivados (no borrados): se pueden eliminar a mano.
