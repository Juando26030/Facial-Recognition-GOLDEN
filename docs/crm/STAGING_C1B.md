# CRM C1b — pantallas de cuentas y contactos (staging) y criterios de éxito

C1b agrega la API, las pantallas de lista y ficha, los contactos con su regla del principal, las notas, el historial y la supresión de datos (Ley 1581). **No hay migración nueva** (las tablas son las de C1a). Se prueba en **staging con datos ficticios**; nada va a `main` ni a producción. Despliegue manual desde la Cloud Shell dueña (lo corre Juan David). Producción sigue con `CRM_ENABLED=0`.

## Antes
1. Tener staging en `0130_crm_cuentas_base` (C1a) y el contador de cuentas fijado: `python scripts/crm_set_counter.py --name account --floor 900000 --apply` (el número es de prueba; el de producción se decide aparte).
2. Pruebas, con el procedimiento del documento 43 (Postgres local y paquetes): `python -m pytest -q tests/test_crm_*.py tests/test_account_sync.py` y `python3 -m pytest -q --noconftest tests/test_crm_texto.py tests/test_crm_c1b_texto.py tests/test_crm_pantallas_texto.py`. Las de `test_crm_pantallas.py` y las tres nuevas de `test_crm_supresion.py` (adelanto, solo admin, servidor local) estaban **sin ejecutar** al entregar C1b-3.
3. Desplegar la rama con `CRM_ENABLED=1` (es el valor por defecto de staging; `manual_deploy.sh` lo muestra antes de desplegar).
4. Usuarios de prueba: uno `comercial`, uno `admin`, uno `coordinador` solo, uno `coordinador` + `comercial`, y un `digitador`.

## Criterios de éxito (todos deben cumplirse)
1. **Interruptor:** con `CRM_ENABLED=0` (probar redesplegando un momento) `/crm` y `/api/crm/meta` dan 404 y el menú no muestra «CRM»; con `1` aparece para comercial, admin y super_admin y también para el doble rol coordinador+comercial; el coordinador solo y el digitador no lo ven y, si escriben `/crm`, vuelven al inicio.
2. **Cuentas:** crear una cuenta con solo el nombre (recibe el siguiente código, sin saltos); crear otra con nombre parecido avisa del duplicado y deja crearla confirmando; la búsqueda encuentra por nombre sin tildes ni mayúsculas, por código, por NIT con o sin puntos, por correo y por nombre de contacto; los filtros de estado, responsable y ciudad y la paginación funcionan y quedan en la dirección de la página.
3. **Control de versión:** abrir la misma cuenta en dos ventanas, guardar en una y luego en la otra: la segunda muestra «Alguien más modificó esta cuenta» y no pisa nada.
4. **Contactos y principal:** el primer contacto queda como principal; «Hacer principal» cambia al otro (uno solo a la vez); archivar al principal pasa el título al siguiente activo; la línea «Contacto principal» de la pestaña Datos se actualiza sin perder lo que se estaba editando.
5. **Cliente de la plataforma (D2/D3):** «Convertir en cliente de la plataforma» crea el cliente con el MISMO número y copia nombre, teléfono (celular primero) y correo del principal; en `/clientes` esos tres campos ya no se pueden editar (409); crear un cliente nuevo desde `/clientes` crea también su cuenta CRM con el mismo número.
6. **Notas e historial:** una nota «sobre un contacto» muestra su nombre; cada cambio aparece en Historial con quién, cuándo y antes → después; borrar una nota ajena como comercial da 403 con mensaje claro.
7. **Permisos:** comercial no ve «Ver archivadas», «Archivar» ni «Suprimir sus datos…»; admin sí. Probar también por la API (`/api/crm/accounts/{id}/archive`, `/contacts/{id}/erase`, `/contacts/{id}/erase-preview`): 403 para comercial.
8. **Supresión con adelanto:** con un contacto que tenga notas propias, datos escritos en el correo/teléfono/contacto de facturación de la cuenta y su nombre dentro de la descripción y de una nota general: el cuadro de confirmación muestra los conteos y el aviso de «revisar a mano»; el botón sigue apagado hasta escribir motivo y nombre; al confirmar, el panel de resultado se queda a la vista con los mismos conteos, «Abrir la descripción» lleva al campo y «Ver las notas» a la pestaña; solo se cierra con «Ya lo revisé». Verificar en la base que no quedan filas del contacto ni valores suyos en `crm_change_log` de la cuenta, y en `audit_actions` (`action='erase'`, `entity='crm_contact'`) solo ids, motivo y conteos.
9. **Servidor local:** con un servidor local de prueba sincronizado, suprimir al principal de una cuenta que sea cliente de la plataforma y esperar un ciclo (o forzarlo desde «Sincronización»): `tenants.contact_*` de esa empresa queda vacío también en el local, aunque ninguna cuenta de personal use esa empresa. En el local no existe el menú CRM.
10. **Visual y sin fugas:** las pantallas se ven bien en claro y oscuro, a 1000, 1100, 1280 y 1500 px y en celular (revisión con `scripts/visual_harness/`, capturas en el reporte de la pieza); los logs de la app no contienen nombres, correos ni teléfonos de los contactos de prueba; `/sistema` no muestra chequeos rojos nuevos.

## Datos de prueba
Todos ficticios (nombres inventados, correos `@ejemplo.test`, teléfonos de relleno). Nada se carga todavía desde SuiteCRM: eso es C1c y necesita antes el aviso a la auditora (`AVISO_AUDITORA.md`).

## Después
Anotar en `docs/15_MIGRACION.md` el resultado (criterios cumplidos y los que no), la fecha, y el identificador del despliegue. Si algo falla, no se avanza a C1c.
