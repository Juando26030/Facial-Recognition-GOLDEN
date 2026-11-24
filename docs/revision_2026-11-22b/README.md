# Segunda pasada — informe final (24-nov-2026)

Rama `saas/revision-integral`. Todo se ensayó en **staging** (`goldenweb-staging`, commit `eea64a61` y anteriores); **nada se ejecutó en producción** y no se creó ningún recurso de nube. Plan: [`00_PLAN_SEGUNDA_PASADA.md`](00_PLAN_SEGUNDA_PASADA.md).
Reportes por rol: [01 aislamiento](01_aislamiento_staging.md) · [02 pruebas en staging](02_pruebas_staging.md) · [03 arquitecto/devops](03_arquitecto_devops.md) · [04 QA](04_qa_desarrollo.md) · [05 ciberseguridad](05_ciberseguridad.md) · planes [06 facturación](06_plan_facturacion_marca.md), [07 sesgo facial](07_plan_modelo_facial_sesgo.md), [08 CSP](08_plan_csp.md), [09 purga local](09_purga_local_y_escarapela_dependientes.md), [10 ramas](10_ramas_para_borrar.md).

## 1. Qué confirmé (con prueba en staging, en pantalla o por código)
- **Aislamiento entre empresas** con `ENFORCE_STAFF_TENANT=1` y `ENFORCE_STAFF_EVENT_SCOPE=1` (solo staging): 5 filtraciones de listas cerradas y re-verificadas; la sexta (asignar una comercial de Golden) solo está cubierta por prueba de texto. Detalle en el reporte 01.
- **Límite del plan** (1 evento al mes): el segundo evento da 403 con mensaje claro.
- **«¿Qué sigue?»** al crear un evento, **confirmación de pago «Activo»**, **menú, ventana «Editar» y tabla de Registro del digitador** (sin desplazamiento horizontal a 320-1920 px): bien.
- **Confirmaciones que piden escribir la palabra** (REABRIR, ELIMINAR, SUPRIMIR, REVOCAR, REEMBOLSAR, DESHABILITAR, BORRAR, CARGAR): con palabra mal escrita o vacía ya no se cierran en silencio; salen con el aviso **dentro de la misma ventana**. Verificado en staging por pantalla y por E2E (REABRIR).
- **Pruebas E2E contra staging (prueba 22):** 12 de 18 corren y pasan (ingreso y menú por rol, registro por cédula, tabla en 5 anchos, reabrir con palabra, `robots`/`noindex`, cotización con campo trampa y datos inválidos, `/health`, candado contra producción). 6 se saltan por falta de datos o equipo (ver §4).
- **Salud de staging** (prueba 21): `/health` 200; los semáforos rojos/amarillos de «Estado del sistema» no son atribuibles a la rama (respaldo viejo porque staging estaba apagado, copia semanal sin configurar, un trabajo fallido de cola sin investigar).
- **Sitio web en staging:** teléfono y correo oficiales, Poppins, `noindex` y `Disallow: /`, cotización «Recibimos su solicitud…» (con el secreto de staging). Republicado el 24-nov con `deploy_sitio.sh goldenweb-staging` (sitio `golden-sitio-298291650070`, commit del sitio `39e4c6f` con el arreglo de los pasos en tableta). Comprobado en el navegador integrado: `robots.txt` con `Disallow: /`, `meta robots noindex`, teléfono `+57 318 098 1752`, WhatsApp y `soporteit@goldenlogisticas.com` oficiales, sin desplazamiento horizontal de la página a 768 px (lo que sobresale son la cinta y el carrusel, que se recortan a propósito). **No revisado a ojo en pantalla:** el aspecto de los pasos en tableta y el resto de anchos (320, 375, 1024, 1440); las capturas del navegador integrado van con retraso.

## 2. Qué corregí en esta pasada
| Qué | Dónde |
|---|---|
| Botón «Copiar» de la contraseña temporal fallaba en el navegador integrado | copiador común (`7e99c59`) |
| 5 filtraciones de listas entre empresas + validación de comercial por cliente | `3e34bcb`, `10e633e` |
| Cotización: `OPTIONS` respondía 204 con cuerpo | `Response` sin cuerpo |
| Confirmaciones con palabra se cerraban en silencio | `toast.js` (`validate`), `gw-confirm-typed.js` y 6 pantallas |
| El desplegable de coordinador del evento nuevo ofrecía coordinadores temporales que el servidor rechaza («El coordinador asignado no es válido») | `event_template_svc.people` usa `coordinator_candidates` |
| «Guardar sin registrar» retirado para todos: solo coordinador o superior corrige sin registrar, con el selector «Estado de registro» | `directory.js` |
| «Material de Golden» (inventario de equipos) oculto al digitador: tarjeta, página y API del checklist | `kiosk_select.html`, `main.py`, `routers/inventory.py` |
| Etiqueta «Recién editado» para quien se corrige sin registrar | `directory.js` |
| Las E2E exigían Postgres local; el evento sintético no pasaba la plantilla de staging; «Reabrir» se buscaba como botón | `tests/e2e/conftest.py`, `test_staging.py` |

## 3. Qué queda (con dueño)
**Juan David:**
- Cambiar la clave de la cuenta de pruebas de staging (quedó escrita en el chat) y crear un digitador de pruebas, una llave de producto de prueba y las direcciones de los servicios público y de biometría si quiere que esas E2E corran.
- **Foto pendiente (sección C de `docs/PRUEBAS_STAGING_2026-11-23.md`):** 10 minutos con tu propia cara; es la prueba más importante de biometría y sigue sin ejecutarse.
- Prueba 13 (suprimir datos → no queda ninguna foto) y la confirmación del escáner con Diego (2004, «se comparó con 2» tras quitar «por verificar»): sin confirmar.
- Sección D (servidor local, purga local con evento devuelto y persona compartida, `autodestruir.ps1`, BitLocker, plazo de gracia): necesita un portátil Windows de pruebas con llave de prueba. **Se deja para el final.**
- Cerrar a mano los eventos terminados que siguen abiertos en producción (0002 y 12345): bloquean el borrado a los 7 días. En staging, el «0002 · Evento Vicepresidencia G12».
- Decidir sobre las ramas a borrar (reporte 10), revisar la propuesta financiera, responder a la auditora (casilla de privacidad, páginas por servicio, textos de IA).
- Hallazgo de seguridad 5: sin corregir, por decisión de dueño pendiente (reporte 05).

**Claude, cuando se autorice:** una corrida completa de la suite en GitHub (incluye 0162-0164, foto pendiente, cotización y SaaS); catálogos propios por empresa (`org_id`, migración y filtro); filtro por empresa en todas las consultas y RLS (160-220 h, plan en el reporte 01); planes 06-09 (facturación y marca, sesgo facial, CSP con medición en report-only, purga local, escarapela de dependientes).

## 4. Qué no pude comprobar
- **Ninguna prueba con base de datos se ejecutó aquí** (no hay Postgres): `test_saas_organizations*`, `test_foto_pendiente_bd`, `test_quote_request`, nodos y las migraciones 0162-0164 con Alembic real. Revisión estática en el reporte 04; falta la corrida de CI.
- **Seis E2E saltadas:** dos del digitador (sin cuenta), «Deshabilitar llave» (sin llaves en staging), escarapela 62 × 99,8 mm (requiere Brother QL-800; la fija `tests/test_impresion_parametros_fijos.py`), `/health` del servicio público y del de biometría (sin direcciones).
- **Cotización con correo real:** solo se comprueba en producción (en staging no sale correo).
- **Scripts PowerShell del servidor local, flujo de GitHub, Poppins vs Agrandir a ojo y que Firebase Hosting deje pasar `/robots.txt` y `/api/public/**` en el sitio nuevo en producción.**
- **Cuenta ajena escribiendo (POST/PUT/DELETE):** el aislamiento solo se barrió en lectura.
- **Un trabajo fallido en la cola de staging:** la causa no se investigó.
- **Cámara `setOff`:** el error de zona muerta temporal sigue en `main`/producción (corregido solo en esta rama).
