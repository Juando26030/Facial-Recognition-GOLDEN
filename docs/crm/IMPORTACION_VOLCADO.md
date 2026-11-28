# Importación del volcado de SuiteCRM (12-nov-2026)

Archivo recibido: `goldenlo_crmgolden.csv`, 390 MB. **No es una exportación por módulo: es la base de datos completa de SuiteCRM 7** (~200 tablas pegadas una tras otra, cada una con su encabezado, sin nombre de tabla). Las relaciones vienen por ids (UUID) y por tablas de enlace. El lector `app/crm/importer/dump.py` reconoce cada tabla por sus columnas (4 s, una sola pasada) y descarta la basura entre tablas.

## Qué trae (filas vivas = sin `deleted=1`)
| Tabla SuiteCRM | Filas (vivas) | Va a nuestro CRM |
|---|---|---|
| accounts (+ accounts_cstm) | 3.889 (3.666) | `crm_accounts` |
| contacts | 9.594 (9.314) | `crm_contacts` (+ enlace accounts_contacts: 12.932) |
| email_addresses + email_rel | 11.110 + 18.331 | correo de cuenta / contacto / lead |
| leads | 27 | `crm_leads` |
| opportunities (+ cstm) | 22.588 (22.407) | `crm_opportunities` (+ enlace con cuenta: 26.837) |
| aos_quotes (+ cstm) | 22.005 (21.743) | `crm_quotes` |
| aos_products_quotes / line_groups | 81.521 (76.179) / 28.649 | `crm_quote_lines` |
| aos_invoices | 6.544 | `crm_proformas` |
| aos_products | 668 (366) | `crm_products` |
| calls / meetings / tasks | 16.891 / 3.019 / 2.975 | `crm_activities` |
| *_audit (historial) | 278.886 | `crm_change_log` (solo cuentas y contactos) |
| users | 59 | se emparejan con el personal de Orum |

No vienen: **notas** (no hay tabla), **archivos** adjuntos (524 documentos: solo el nombre; los archivos no están en el volcado).

## Cómo se corresponde cada campo
**Cuenta**: `name`→nombre · `sic_code`→**NIT** (1.201 llenos) · `accounts_cstm.codigo_c`→**número de cuenta** (3.570; 3.487 únicos: hay repetidos; máximo 181111) · `estado_c`→estado · `phone_office`→teléfono · `billing_*`/`shipping_*`→direcciones · `description`→descripción · `date_entered`→fecha de origen · `assigned_user_id`→responsable · `plazo_pago_c`,`dias_para_pago_c`,`cierre_facturacion_c`,`porcentaje_agencia_c`,`contacto_cobro_c`,`contacto_cobro_tel_c`→condiciones de cobro · correo ← `email_rel`.
**Contacto**: nombres, `title`→cargo, `phone_work`/`phone_mobile`, correo principal ← `email_rel`, `description`→notas; cuenta ← `accounts_contacts` (2 contactos están en 2 cuentas; 198 sin cuenta).
**Oportunidad**: `name`, `amount`, `currency_id` (COP casi siempre), `date_closed`→cierre esperado, `sales_stage`→etapa (Closed Won 11.086 · Closed Lost 7.707 · Value Proposition 2.528 · Prospecting 1.236 · resto <30), `probability`, `lead_source`→fuente, `opportunity_type`, `next_step`, `description`, `opportunities_cstm.codigo_c`→**código** (11.127; máx. 23060002, con repetidos), cuenta ← `accounts_opportunities` (133 sin cuenta).
**Cotización**: `number`, `name`→título, `stage`→etapa, `approval_status`, `invoice_status`, `expiration`→válida hasta, `term` (Net 30/15), totales, líneas por `parent_id`, cuenta `billing_account_id`, contacto `billing_contact_id`, oportunidad `opportunity_id`, evento en `quotes_cstm`.
**Actividades**: `parent_type`/`parent_id` (Accounts 14.475 · Opportunities 2.328 · Leads 83 en llamadas; similar en reuniones y tareas), `status` (Held/Planned/Not Held · Completed/Pending Input…), `date_start`, `description`.

## Lo que HOY no cabe en nuestro CRM (para que «quede igual»)
1. **Estado de cuenta**: SuiteCRM tiene Activo 3.076 · Masivo 463 · Inactivo 148 · **NoGestionar 79 · Liquidado 76 · Moroso 23 · ConRestriccion 1**. Nosotros: activo/inactivo/masivo. → ampliar la lista (solo código, sin migración).
2. **Categoría de cliente** (`categoria_c`: ClienteVIP 84, A 16, B 23, C 268), **tipo de cuenta** (`account_type`: Agencias 912 · Customer 668 · Asociaciones 132 · BTL 100 · OPC 82 …), **industria**, **sitio web** (1.859 reales), teléfono alterno y fax → columnas nuevas en cuentas.
3. **Contactos**: saludo, departamento, fuente, dirección, fecha de nacimiento, «no llamar», otros teléfonos.
4. **Oportunidades**: `codbase_c`, `dateproject_c`, `facturahistorico_c`, `gestorini_c`, `gestorfin_c`.
5. **Cotizaciones**: descuento «por monto» en 617 líneas (solo manejamos %), IVA 5/16/19/0 por línea (cabe), etapas propias *Tarifarios 165 · Opcionales 46 · Licitaciones 14* (no existen en nuestras 5 etapas), grupos de líneas con nombre (153), moneda MXN (2).
6. **Facturas** (6.544 con 14.405 líneas): nuestra proforma solo guarda el total.
7. **Actividades** colgadas de Proyectos (176), Casos (104) o Contratos: no tenemos dónde colgarlas.
8. **Historial** de oportunidades y cotizaciones (≈ 270.000 cambios): `crm_change_log` solo acepta cuenta y contacto.

**Solución propuesta (migración 0142, columnas que aceptan vacío):** columnas propias `category`, `account_type`, `industry`, `website` en cuentas y una columna `legacy_json` (texto JSON, solo lectura) en cuentas, contactos, leads, oportunidades, cotizaciones, proformas, actividades y productos que **guarda todo lo que no tiene columna**, con el nombre original de SuiteCRM. Así nada se pierde y lo nuevo nuestro queda vacío.

## Reglas de la importación (propuestas)
- **Idempotente**: cada fila guarda su id de SuiteCRM (`legacy_sugar_id`); correr dos veces no duplica.
- **Códigos originales se respetan** cuando son únicos y numéricos; los repetidos o vacíos reciben el siguiente del contador y el original queda en `legacy_json`. Después se sube el piso del contador por encima del máximo (hoy 181111 en cuentas y 23060002 en oportunidades: hay que decidir si el contador de oportunidades sigue esa numeración o parte de un piso razonable).
- **Borrados** (`deleted=1`) no se importan.
- **Responsables**: el usuario de SuiteCRM se empareja con el personal por nombre/correo en un paso previo que aprueba el administrador; sin pareja queda sin responsable y el nombre original en `legacy_json`.
- **Fechas** en UTC como vienen; dinero en COP (MXN se conserva con su moneda).
- Pasos: 1) *muestra* (20 filas por tabla, no guarda) → 2) *prueba en seco* (todo, no guarda, informe de rechazos) → 3) *aplicar*. Corre como trabajo largo (Cloud Run Job), nunca en la petición web. Los archivos se borran al terminar.
- Sin datos personales en logs ni informes (solo conteos y motivos).

## Estado (13-nov-2026)
Hecho: lector del volcado (`dump.py`), migración 0142, **conversor** `app/crm/importer/convert.py` + `scripts/crm_dump_to_csv.py` (volcado → 7 archivos por tipo con los encabezados de `formats.py`), y el importador existente (`runner.py`/`more.py`) ya guarda estado, categoría, tipo, industria, sitio web y `legacy_json`.
Cómo se corre: 1) `python scripts/crm_dump_to_csv.py <volcado.csv> <carpeta fuera del repo>` (solo imprime conteos) → 2) en `/crm/importar` (admin) se suben los archivos, «Muestra» → «Prueba completa» → «Cargar de verdad».
Resultado de la conversión con el volcado real (conteos): cuentas 3.666 · contactos 9.116 · oportunidades 22.274 · actividades 21.279 (llamadas 15.949, reuniones 2.735, tareas 2.595) · cotizaciones 21.575 con 61.098 líneas · productos 366. Todos los archivos pesan menos de 25 MB (tope del importador; el mayor, 12 MB).
Decisiones tomadas por el conversor (todas dejan el original en `legacy_json`): 27 cuentas con el mismo nombre → la repetida lleva « (cuenta <número>)» para poder ligar por nombre; 31 códigos de cuenta, 134 de oportunidad y 3 números de cotización repetidos → reciben el siguiente del contador; 7 teléfonos de cuenta y 4 de contacto/cargo por encima del tope → recortados; importes con 8 decimales → 2; descuento en pesos (522 líneas) → porcentaje; moneda `-99` → COP; etapas de cotización propias (Tarifarios, Opcionales, Licitaciones) → borrador con la etapa original anotada.
Quedan fuera (no tienen dónde vivir hoy): leads sueltos, actividades de Proyectos/Casos/Contratos (≈ 280), 198 contactos sin cuenta, 133 oportunidades y 169 cotizaciones sin cuenta viva, facturas (proformas), historial de cambios, notas y archivos. Responsables: sin emparejar (todo queda a nombre de quien importa; el usuario original en `legacy_json`).
Falta: ejecutarlo en staging (lo hace el administrador con los archivos), verificar conteos contra este informe y recién ahí producción (con respaldo de Neon).
