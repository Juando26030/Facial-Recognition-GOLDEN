# Importador de SuiteCRM (C1c-1)

Cuentas y contactos, desde CSV exportados de SuiteCRM 7 (encabezados en español o inglés, delimitador y codificación detectados). Solo administradores.

- **Modos:** `sample` (20 filas por archivo, nada se guarda), `dry_run` (todo el archivo, nada se guarda), `apply` (guarda).
- **Seguridad:** `apply` exige `CRM_IMPORT_APPLY=1` (staging 1, producción 0 → 403 «La carga real está desactivada en este entorno»), una corrida `dry_run` terminada con los MISMOS archivos (SHA-256) y escribir «CARGAR».
- **Filas malas:** un SAVEPOINT por fila; se rechazan con número de fila y motivo SIN valores. Idempotente por `legacy_sugar_id`.
- **Números:** conserva el «Número de cuenta» de SuiteCRM y sube el contador `account` por encima del mayor (`bump_floor`).
- **Emparejamiento:** clientes de la plataforma ↔ cuentas de SuiteCRM (`seguro` ≥95 con margen ≥10 y mutuo; `dudoso` 70–94; `sin_pareja` <70). Solo se aplican las parejas APROBADAS: el cliente pasa al número de SuiteCRM y el hexadecimal queda en `legacy_client_code`.
- **Archivos:** en `crm/imports/<id>/`, se borran SIEMPRE al terminar. Trabajo por la cola (`crm_import`), nunca en un hilo en Cloud Run.
- **Probar sin datos reales:** `python scripts/crm_make_synthetic_suitecrm.py /tmp/sint 50`.
- **Datos reales:** NO se cargan hasta que Juan David lo diga y la auditora haya recibido el aviso.

## DECISIÓN / pendiente
- La pantalla `/crm/importar` aún no está (hoy se usa la API `/api/crm/import/runs`); es lo siguiente.
- Un contacto cuya cuenta no se reconoce por nombre se rechaza (se cuenta en `without_account`).
- Oportunidades, actividades, productos y cotizaciones de SuiteCRM llegan en C1c-2.
