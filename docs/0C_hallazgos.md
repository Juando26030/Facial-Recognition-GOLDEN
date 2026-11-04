# 0C · Línea base de seguridad — hallazgos (pasada 1, 2-nov-2026)

Revisión de código de **solo lectura** sobre `main` = 0fd00fc, hecha por Claude (caja blanca, a mano, con búsquedas dirigidas). **No es la 0C completa:**
faltan escáneres automáticos (Semgrep/Bandit, pip-audit, gitleaks, Trivy: no se pueden instalar en este entorno; van al CI), la prueba dinámica en staging y la
revisión de infraestructura. Severidades: crítica / alta / media / baja / info.

## Hallazgos
| # | Severidad | Dónde | Hallazgo | Propuesta |
|---|---|---|---|---|
| H1 | **Media hoy · Alta antes de ofrecer el SaaS** | `app/auth.py` `get_event_for_staff` (184 usos) | Un usuario del personal con rol coordinador o superior accede a **cualquier evento por su id**: la consulta es `Event.id == event_id` sin comparar `staff.tenant_id` con `event.tenant_id`. Hoy es el diseño (el personal es de Golden, «alcance de tenant»), pero `StaffUser.tenant_id` existe y, el día que otra empresa tenga su propio coordinador, vería eventos ajenos. Los roles digitador/cliente sí quedan acotados por `EventStaffAuthorization`. | Filtrar por tenant (`staff.tenant_id` nulo = global, solo super_admin) dentro de `get_event_for_staff` y probarlo con dos tenants. Es un cambio central: va en su PR, con pruebas, antes del SaaS. |
| H2 | Baja | `app/formlib.py` cupos | Se descartaban en silencio los cupos desde el 31. **Corregido** (PR #6, en producción). Queda sin aviso si una regla se descarta por ser inválida. | Devolver un aviso al guardar cuando se descarta una regla. |
| H3 | Baja | `app/privacy.py`, `app/event_transfer.py` | Varios `text(f"…")` con SQL armado por texto. Revisados uno por uno: solo interpolan constantes internas (lista fija de tablas, subconsulta fija, nombre de secuencia que devuelve la base); los datos van como parámetros. | Sin acción; dejar comentario «constante interna» y que Semgrep los marque como aceptados. |
| H4 | Info | `app/main.py:134` | `SECRET_KEY` tiene un valor inseguro por defecto **solo fuera de producción**; en producción la app no arranca sin la variable. Correcto. | Ninguna. |

## Revisado y sin hallazgos
- **Rutas públicas** (sin sesión): `/privacidad`, `/terminos`, `/reembolsos`, formularios `/f/…`, `/email-assets/…` (nombre UUID, validación de ruta, públicas a propósito), redirecciones de `/kiosk/{id}/facial|cedula`. Coinciden con lo esperado.
- **`/internal/*`**: única puerta `google_invoker` (token OIDC de Google, audiencia y cuenta del entorno; sin configurar = 403).
- **Webhook de Wompi**: checksum SHA-256 con comparación en tiempo constante; sin secreto configurado se rechaza.
- **CSRF**: cookie SameSite=Lax + verificación de `Origin` en peticiones que cambian estado. Cookie de sesión `https_only` en producción.
- **Contraseñas**: bcrypt. Inicio de sesión del personal con bloqueo por intentos (`routers/auth.py`).
- **XSS**: el JSON que se inyecta en `<script>` escapa `</`; el HTML enriquecido de formularios se limpia con lista blanca **en el servidor al guardar y otra vez en el navegador al pintar** (`app/richtext.py`, `static/js/rich-text.js`).
- **Código peligroso**: sin `eval`, `exec`, `pickle`, `yaml.load` inseguro, `shell=True` ni `verify=False` en `app/`.
- **Historial de git**: sin secretos reales (ver `0B_inventario.md`).

## Aún sin revisar (siguientes pasadas)
Subida de archivos y URLs firmadas (`uploads.py`, `storage.py`), tokens de enlaces de aceptación, SSRF (descarga de imágenes por URL), datos personales en logs (`obs.py`), manejo de `FACE_ENCRYPTION_KEY`, permisos por rol endpoint por endpoint (matriz de la Fase 3), cuentas de servicio/buckets/Secret Manager/Neon/Cloudflare (los comandos de nube los corre Juan David).

## Preguntas para iniciar la parte dinámica (plan 4c)
1. Proveedor y **tope de gasto** de la clave de IA exclusiva para las pruebas con Strix (la crea Juan David; nunca en el repo ni en el chat).
2. Ventana de fechas para las pruebas en staging (con datos ficticios y una rama de respaldo de Neon).
3. ¿Quieres además una prueba de penetración humana externa (recomendada antes del SaaS)?

## Línea base de escáneres limpia (2026-11-04)
- **Bandit alto (5, B324 sha1/md5):** ids/etags/huellas, no seguridad (`rule_sig` de cupos, etag del directorio, huella de cliente, build del service worker, MD5 de GCS). Ahora `usedforsecurity=False`; el VALOR del hash no cambia (los conteos de cupos y datos guardados quedan iguales).
- **Bandit medio:** B608 (SQL con f-string) revisados uno por uno: solo nombres internos de tablas/columnas/subconsultas; lo del usuario va enlazado (`# nosec B608` con el porqué). B310 (urlopen): URLs https fijas (Wompi, FX, Microsoft Graph, Google); `# nosec B310`. B704: `Markup` con un entero acotado 30-80.
- **gitleaks (7):** todos falsos positivos (contraseñas de prueba inventadas en `tests/`); permitidos con cadenas exactas en `.gitleaks.toml`. Ninguna clave real.
- **CI (`seguridad.yml`):** gitleaks y Bandit ALTO bloquean; Bandit medio, Semgrep y pip-audit siguen informativos (Semgrep nunca llegó a correr antes: se revisa su primer informe).
