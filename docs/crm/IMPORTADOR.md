# Importador de SuiteCRM (C1c-1 y C1c-2)

Cuentas, contactos, productos, oportunidades, actividades, cotizaciones (con sus líneas) y proformas, desde CSV exportados de SuiteCRM 7 (encabezados en español o inglés, delimitador y codificación detectados). Solo administradores.

- **Modos:** `sample` (20 filas por archivo, nada se guarda), `dry_run` (todo el archivo, nada se guarda), `apply` (guarda).
- **Seguridad:** `apply` exige `CRM_IMPORT_APPLY=1` (staging 1, producción 0 → 403 «La carga real está desactivada en este entorno»), una corrida `dry_run` terminada con los MISMOS archivos (SHA-256) y escribir «CARGAR».
- **Filas malas:** un SAVEPOINT por fila; se rechazan con número de fila y motivo SIN valores. Idempotente por `legacy_sugar_id`.
- **Números:** conserva el «Número de cuenta» de SuiteCRM y sube el contador `account` por encima del mayor (`bump_floor`).
- **Emparejamiento:** clientes de la plataforma ↔ cuentas de SuiteCRM (`seguro` ≥95 con margen ≥10 y mutuo; `dudoso` 70–94; `sin_pareja` <70). Solo se aplican las parejas APROBADAS: el cliente pasa al número de SuiteCRM y el hexadecimal queda en `legacy_client_code`.
- **Archivos:** en `crm/imports/<id>/`, se borran SIEMPRE al terminar. Trabajo por la cola (`crm_import`), nunca en un hilo en Cloud Run.
- **Probar sin datos reales:** `python scripts/crm_make_synthetic_suitecrm.py /tmp/sint 50`.
- **Datos reales:** NO se cargan hasta que Juan David lo diga y la auditora haya recibido el aviso.

## Archivos y orden (C1c-2)
Se procesan SIEMPRE en este orden, en una sola corrida: cuentas → contactos → productos → oportunidades → actividades → cotizaciones (+ líneas) → proformas. Cada archivo es opcional; las referencias se resuelven por el id de SuiteCRM (`legacy_sugar_id`) o por el nombre de la cuenta/oportunidad, contra lo que ya está en la base **y** contra lo que traen los archivos de la misma corrida (así la prueba en seco se parece a la carga real).

| Archivo | Obligatorio | Cómo se liga | Notas |
|---|---|---|---|
| productos | Nombre | — | SKU repetido se rechaza; impuesto 19 % por defecto |
| oportunidades | Nombre, Nombre de la cuenta | cuenta por nombre | «Código Proyecto» se conserva (sube el contador `event`); etapa por tabla de nombres (inglés/español) o por tipo si el admin renombró; ganada/perdida se guardan como resultado directo |
| actividades | Asunto | oportunidad (id o nombre) y/o cuenta | Llamada/Reunión/Tarea/Nota; Held→hecha, Not Held→cancelada; sin vínculo conocido se rechaza |
| cotizaciones | Nombre de la cuenta | cuenta por nombre, oportunidad opcional | número se conserva (contador `quote`); totales los calcula el servidor desde las líneas |
| líneas de cotización | Nombre | cotización por id o número | se leen junto con el archivo de cotizaciones |
| proformas | Nombre de la cuenta | cuenta por nombre, cotización opcional | número se conserva (contador `proforma`); Paid→pagado, Unpaid→no pagado |

Valores: fechas `año-mes-día` o `día/mes/año`; dinero con `1.500.000,50` o `1,500,000.50`; moneda no reconocida → COP (se cuenta en el informe).

## DECISIÓN
- **Lo importado no dispara efectos.** Una oportunidad ganada que llega de SuiteCRM se guarda como ganada pero NO crea cliente ni evento (se ve «Crear el evento» en su ficha); no se escribe historial de cambios; no hay correos ni avisos.
- **Cotización sin líneas pero con total:** una sola línea «Total importado de SuiteCRM», sin impuesto, para que el total coincida con el origen.
- **Etapa no reconocida:** primera etapa abierta del embudo por defecto, contada en el informe (`stage_unmapped`).
- **Las líneas no se ligan al catálogo de productos** (conservan el nombre tal como venía).
- Un contacto, oportunidad, cotización o proforma cuya cuenta no se reconoce por nombre se rechaza (`without_account`); una actividad sin oportunidad ni cuenta conocidas, también (`unlinked`).
- El informe nunca trae valores de datos: solo número de fila y motivo.
