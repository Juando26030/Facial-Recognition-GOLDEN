# Fase 4: descargas de «bases de datos de cuentas»

Dos descargas (Excel `.xlsx` por defecto; `format=csv` da CSV UTF-8 con BOM). Código: `app/routers/downloads.py`; permisos en UN solo lugar: `app/download_perms.py`.

| Base | Endpoint | Contenido |
|---|---|---|
| A. Digitadores | `GET /api/staff/export?kind=digitadores[&format=csv]` | cédula, nombre, teléfono, cliente, eventos en que ha participado, estado, fecha de creación |
| B. Clientes | `GET /api/tenants/export[?format=csv][&tenant_id=]` | hoja «Clientes» (código, empresa, contacto, teléfono, correo, estado, n.º de eventos) y hoja «Cuentas de cliente» (nombre, teléfono, correo, estado); el CSV lleva solo la hoja de empresas |

Nunca salen contraseñas, hashes, tokens ni datos de salud.

## Matriz rol × base
| Rol | A. Digitadores | B. Clientes |
|---|---|---|
| digitador (temporal) | no | no |
| cliente | no | no |
| coordinador | sí | no |
| comercial | sí | sí |
| coordinador + comercial (doble rol) | sí | sí |
| admin | sí | sí |
| super_admin | sí | sí |
| contabilidad / inventario (NO existen aún) | previsto: sí | previsto: no (a definir) |

Agregar un rol nuevo: una palabra en `DOWNLOAD_ROLES` de `app/download_perms.py` (más el rol en `STAFF_ROLES` cuando se cree). Se evalúa con `effective_roles`.

## Seguridad
- **Aislamiento:** con `ENFORCE_STAFF_TENANT=1` solo salen las cuentas/clientes del cliente de quien descarga (`tenant_id` ajeno en B da 404). Con `ENFORCE_STAFF_EVENT_SCOPE=1`, coordinador/comercial ven solo digitadores y clientes de SUS eventos, y de cada digitador solo sus eventos visibles. Ambos interruptores siguen apagados por decisión del dueño; el código ya los respeta.
- **Fórmulas:** todo texto pasa por `app.xlsafe.safe_cell` (prefijo `'` en `= @ tab` y en `+`/`-` que no sean un teléfono). Los teléfonos con `+57…` se dejan tal cual (convención del proyecto).
- **Respuesta:** `Cache-Control: no-store`, `Content-Disposition: attachment` con nombre fijo `base_<tipo>_<AAAAMMDD>.<ext>`, `X-Content-Type-Options: nosniff`.
- **Auditoría:** `audit_actions` (solo INSERT): acción `export`, entidad `base_digitadores` / `base_clientes`, detalle «N filas, formato». Sin cédulas ni nombres.
- **Tope:** 6 descargas por hora por usuario (`rate_limit_events`, tipo `export_base`, sin IP); la 7.ª da 429. Un acceso denegado no consume cupo ni deja auditoría.

## Interfaz
Botones «Base de digitadores» y «Base de clientes» en Clientes (`/clientes`) y Usuarios de staff (`/admin/staff`), visibles solo a quien tiene permiso (calculado en `app/main.py` con `download_perms.can_download_roles`).

## Pruebas
`tests/test_descargas_bases.py`: matriz de roles, doble rol, extensibilidad, contenido sin secretos, tenant y alcance por evento, fórmulas (xlsx y csv), auditoría, tope.
