# Fase 0C — Hallazgos, pasada 2 (equipo rojo de lectura de código, ronda cruzada)

Fecha: 2-nov-2026. Método: 5 revisores independientes de solo lectura (autorización, archivos, sesiones/pagos, inyección/frontend, datos/operación) → cada informe fue criticado por otro revisor sin saber quién lo escribió → consolidación y verificación por muestreo.
Resultado de la ronda cruzada: **0 falsos positivos** en 69 hallazgos revisados (todos confirmados o parciales) y 21 hallazgos nuevos. Nada se ejecutó contra producción; no hay datos personales ni secretos en este documento.
**Críticos: 0. Altos: 7 familias (abajo). Todos los altos se arreglan antes de la Fase 1A.**

## ALTOS (bloquean el cierre de 0C)
| Id | Familia | Dónde (resumen) | Rol necesario | Arreglo |
|---|---|---|---|---|
| ALTA-1 | XSS almacenado en el panel (nombres sin escapar en `innerHTML`) | `static/js/toast.js` (D1), `esc` incompleto en quioscos y directorio (D2, D5), nombres de evento/cliente/ubicación (D3), usuarios y personal (D4, C2, C-N1) | Anónimo (cédula/nombre en formulario público) o coordinador→admin→super_admin | Un solo `esc()` compartido que escape `& < > " '`; `showToast/showConfirm` con `textContent`; quitar `onclick` con valores interpolados; validar `username`/`full_name`/`name` en el servidor |
| ALTA-2 | SVG como logo servido en línea, sin cabeceras de seguridad | `parametros.py:122`, `aceptar.py` logo público, `event_transfer.py` (B1, D-N1, B-N2, D8) | coordinador | Quitar `.svg` de logos (y del import de eventos); middleware global con `X-Content-Type-Options: nosniff`, CSP (`frame-ancestors`, `object-src 'none'`, `base-uri`, `form-action`), `X-Frame-Options`, `Referrer-Policy`; archivos subidos con `Content-Disposition`/CSP `sandbox` |
| ALTA-3 | Consentimientos biométricos fabricables y con fecha libre | `routers/consents.py` (E1, A5, E-N2) | digitador | Ignorar `at` del cliente (usar hora del servidor, tope), validar `text_hash` contra el texto vigente, exigir que la persona esté en el evento, límite de tasa |
| ALTA-4 | `/aceptar` sin sesión: borra rostro y fija fecha cuando `birth_date` es NULL | `aceptar.py:162-170, 241-273` (C1, C-N3, A3) | Anónimo + conocer una cédula | No aceptar fecha tecleada para fijar `birth_date`; exigir token/QR o segundo factor para cualquier efecto destructivo; contador de fallos por cédula (C8) |
| ALTA-5 | Formulario público reescribe datos de personas ya registradas, incluida la marca de menor | `formsvc.py:484-514` (A4, C3, C-N2) | Anónimo + cédula invitada | No sobrescribir `birth_date`/`is_biometric_enabled`/correo de una persona existente desde el formulario; solo completar vacíos |
| ALTA-6 | Toma de cuenta por cambio de correo | `staff.py:139-152` + recuperación de contraseña (A1, A11) | admin | `set_staff_email` solo sobre roles inferiores y mismo tenant; verificar el correo nuevo; rotar sesiones al restablecer |
| ALTA-7 | Falta de comprobación de tenant y de evento (diseño de un solo tenant) | `get_event_for_staff` (H1), todo `events.py` incl. `update_event`, `staff.py` (N1), asignar/revocar personal de evento (N2), `coordinator_staff_id` (N3), A6, A9 | coordinador/admin | Pasar todo `events.py` por `get_event_for_staff` y comparar tenant (nulo = global solo super_admin); pruebas con dos tenants. **Hoy: efecto bajo (un solo tenant); alta antes del SaaS** |

## MEDIOS (con fecha; se agrupan en PR)
A2 asignación masiva en `PUT /users` · A6/A7 alcance por tenant sin pertenencia al evento · B2/D7/E6 inyección de fórmulas en Excel exportados · B3 ZIP/imagen sin tope (bomba) · B-N1 imagen de gastos sin tope de píxeles · C4/C15 cédula tecleada no amarrada a la invitación · C5 pago aprobado sin inscripción · C7 bloqueo de login por usuario sin IP (denegación al super_admin) · C8 sin contador por cédula · C11 contraseñas creadas sin política · D6 `err` sin escapar en carga masiva · D9 `xlsx`/`jszip` de CDN sin `integrity` y traductor en el mismo origen · E2 cédulas en `jobs.payload_json` y `web_acceptances` tras supresión · E3 errores sin enmascarar en `jobs.last_error` · E4 directorio con datos personales a rol `cliente` · E5 foto sin `face_captured_at` (no entra a la purga) · E8 los 3 servicios comparten cuenta y secretos · E9/E-N5 `SECRET_KEY` por defecto en Jobs y scripts (en la app web ya falla en producción: verificado) · E-N1 revocación por evento tratada como global.

## BAJOS / INFORMATIVOS
A10, A12, B4-B9, C6, C9, C10, C12-C14, C-N4, C-N5, D10-D15, D-N2-N4, E7, E10-E15, E-N3 (escáneres de CI con `continue-on-error`: quitar al cerrar 0C), E-N4.

## Verificado por mí en el código
- B1: `.svg` permitido, sin CSP ni `nosniff` en toda la app → **confirmado**.
- N5: `main.py:38` impide arrancar en producción sin `SECRET_KEY`; el valor por defecto solo queda en `consent.py`, `faces.py`, `uploads.py` (Jobs y scripts) → **baja, endurecer**.
- `update_event` y `events.py` no llaman a `get_event_for_staff` (confirmado por dos revisores).

## Plan de arreglos (ramas pequeñas, con pruebas, primero staging; una entrega a producción por semana como máximo)
1. `fix/0c-xss` (ALTA-1) · 2. `fix/0c-cabeceras-svg` (ALTA-2) · 3. `fix/0c-consentimientos` (ALTA-3) · 4. `fix/0c-aceptar-formulario` (ALTA-4 y 5) · 5. `fix/0c-staff-correo` (ALTA-6) · 6. `fix/0c-tenant` (ALTA-7) · 7. medios agrupados.
Producción solo con autorización escrita de Juan David para ESA entrega.
