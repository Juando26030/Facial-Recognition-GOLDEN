# Plan 06 · Facturación y marca propia por empresa del SaaS

Fecha: 23-nov-2026 · Rama `saas/revision-integral` · Es un PLAN (no hay código nuevo). Lo ejecuta otro desarrollador sin preguntar; lo que decide Juan David está al final.
Complementa a `docs/27_SAAS_EMPRESAS.md` (piezas 6, 7 y 8 de §5), al reporte `docs/revision_2026-11-22/07_saas_prospectos_finanzas_planes.md` (S5, S5b, S6) y a `docs/PROPUESTA_FINANCIERA_SAAS_2026-11-22.md` (los precios son PROPUESTA, no decisión).

## 0. En palabras sencillas (para Juan David)

- **Facturación** = que cada empresa que contrate la plataforma tenga una pantalla «Estado de cuenta» (cuánto usó, cuánto debe, qué pagó) y que Golden pueda cobrarle y suspenderla si no paga. Hoy **no existe nada de eso**.
- **Marca propia** = que la empresa vea SU logo, SUS colores y SU nombre (y que sus correos salgan con su nombre), no los de Golden. Hoy la marca se puede cambiar **por evento** (logo y color), pero no **por empresa**, y los correos y varias pantallas dicen «Golden» fijo.
- Las dos cosas son independientes: se pueden hacer en cualquier orden. La marca es lo que primero pide un cliente; la facturación es lo que primero necesita Golden para cobrar. Recomendación en §6.

## 1. Qué existe hoy (verificado en el código)

### 1.1 Empresas, planes y límites
| Qué | Dónde | Estado |
|---|---|---|
| Tabla `organizations` | `app/models.py` líneas 28-42; migración `alembic/versions/0162_organizations.py` | Columnas: `id, slug, name, legal_name, nit, contact_email, contact_phone, plan, entitlements_json, status, created_at, notes`. **No tiene ninguna columna de marca ni de cobro.** |
| `tenants.org_id`, `staff_users.org_id` | `app/models.py` línea 57 y 249 | NULL o 1 = Golden. Sin llave foránea. |
| Planes (`interno`, `basico`, `pro`, `empresa`) y límites | `app/orgs.py` (`PLANS`, `entitlement`, `check_limit`, `usage`) | Funciona. |
| La función `own_brand` («Marca propia») | `app/orgs.py` líneas 28, 39, 44-47 | **Está definida y se puede activar o apagar por empresa, pero ningún otro archivo del código la consulta** (`grep -rn own_brand app templates static` solo devuelve `app/orgs.py`). Es decir: hoy es una casilla sin efecto. |
| Pantalla «Empresas (SaaS)» y API | `templates/plataforma.html`, `static/js/plataforma.js`, `app/routers/platform.py` (rutas `/catalog`, `/orgs`, `/orgs/{id}`, suspender, reactivar, `/admin`, `/usage`) | Crea, edita, suspende, ve consumo. No cobra. |
| Consumo medible | `orgs.usage()` (`app/orgs.py`) | Eventos creados este mes, eventos totales, asistentes totales, evento más grande, cuentas activas, clientes. La persona `PRUEBA` no cuenta. |
| Límite realmente aplicado | `app/routers/events.py` línea 438 (`create_event`) | Solo «eventos por mes». Los demás límites (usuarios, asistentes, facial, servidor local, formularios con pago, marca propia) están definidos pero **no frenan nada todavía** (`docs/27` §1 y §5, pieza 7). |

### 1.2 Facturación y cobro
- **No hay** tablas de cargos, facturas, pagos recibidos ni suscripciones. `grep -n "class .*Invoice\|class .*Billing\|class .*Charge" app/models.py` no devuelve nada.
- **No confundir:** la pantalla «Cuentas de cobro» (`templates/cuentas_cobro.html`, `app/routers/payment_accounts.py`, tabla `payment_accounts`, doc `docs/23_COBROS_WOMPI_MULTICUENTA.md`) sirve para que un TERCERO preste su cuenta Wompi y SUS formularios de inscripción cobren a SU nombre. No sirve para que Golden le cobre la suscripción a una empresa.
- Lo único parecido a «facturación» interna es `events.billed_at` (`app/models.py` línea 354): la fecha en que un evento de Golden pasó al estado «Facturado». Es del CRM/operación de Golden, no del SaaS.
- Wompi ya está integrado para formularios (`app/wompi.py`, `app/payment_accounts.py`, `app/routers/form_payments.py`), de modo que cobrar una suscripción con un enlace de pago es técnicamente cercano. La factura electrónica DIAN **no existe** en el código.

### 1.3 Marca (logo, colores, nombre, dominio)
| Superficie | Cómo se decide hoy | Archivo |
|---|---|---|
| Logo del encabezado de las páginas de un evento | Por EVENTO: `events.logo_mode` (`default` / `hidden` / `custom`), `logo_path`, `logo_height` (30-80 px), `logo_fit`. Por defecto el de Golden (`DEFAULT_LOGO_URL` o `static/img/logo-golden.png`) | `app/models.py` 323-329; `app/main.py` 340-375 (`default_logo_url`, `event_logo_url`, `event_logo_attrs`); `app/routers/parametros.py` 205-265 |
| Tamaño del logo de Golden | UN valor global (`app_settings`, clave `golden_logo_height`) | `app/logosize.py` |
| Color de marca | Por EVENTO: `events.brand_color` (`#rrggbb`, exige contraste AA 4,5:1), se inyecta como variables CSS `--gw-gold-*` | `app/brandcolor.py`; usado en `app/routers/aceptar.py` 221, `forms_public.py` 271, `certificates_public.py` 61, `stats_links.py` 128, `contacts.py` 36 |
| Nombre de la sociedad en pantalla | UN valor global por variable de entorno `COMPANY_NAME` | `app/main.py` línea 386 |
| Datos legales del pie público (nombre, NIT, dirección, teléfono, correos) | UN conjunto global por variables `LEGAL_*` / `COMPANY_NIT` / `PRIVACY_EMAIL` con valores de Golden por defecto | `app/legal.py` `info()`; `templates/_legal_footer.html` |
| Textos legales del reconocimiento facial | LITERALES de la auditora para Golden | `app/legal_texts_data.py`, `app/legal_texts.py` (INAMOVIBLE, no se editan) |
| Remitente de correo | UNA cuenta global: Microsoft Graph (`GRAPH_SENDER`) o SMTP (`SMTP_FROM`), `no-reply@golden.local` si falta todo | `app/mailer.py` líneas 105-110 |
| Textos de correos con «Golden» fijo | «Tu cuenta de GoldenWeb 2.0…», «…plataforma de acreditación de Golden Eventos y Logística» | `app/staff_credentials.py` 47-48, 92-95; `app/notifications.py` 49-51; `app/routers/event_report.py` 38 |
| Pase de billetera digital | Constante `BRAND = "Golden Eventos y Logística S.A.S."`, «Golden Eventos» | `app/wallet.py` 18, 70, 113 |
| Portada del informe final | Logo del evento si es propio; si no, el de Golden; con logo propio, una marca pequeña de Golden en el pie | `app/report_book.py` 4-25 |
| Pantalla de ingreso | Logo y título «GoldenWeb 2.0» fijos | `templates/login.html` 7, 25-26 |
| Resto de pantallas | 61 plantillas mencionan «Golden» en el texto (`grep -rln Golden templates` = 61) | `templates/` |
| Dominio | Un solo host de aplicación (`PUBLIC_BASE_URL`, hoy `app.golden-eventos.com`); la CSRF por Origen solo acepta ese host y el que llega en la petición | `app/publicurl.py`; `app/main.py` 144-163 |
| Correo de aceptación de rostro | Solo eventos propios de Golden (`controller_mode == 'golden'`) | `app/acceptmail.py` 4, 46 |

### 1.4 Escarapela e impresión (zona protegida)
- La escarapela se compone en el navegador (`static/js/badge-render.js`, `static/js/label-compose.js`, `static/js/shared-print.js`) con los elementos que el cliente diseñó en el diseñador (`templates/badge_editor.html`); un logo es un elemento de imagen (`image_static`, subido con `app/routers/badges.py`). **El logo de la escarapela ya es del cliente, por evento; no depende de la marca de Golden.**
- La impresión está fijada como INAMOVIBLE (`docs/IMPRESION_PARAMETROS_INAMOVIBLES.md`, `CLAUDE.md`): página siempre 62 × 99,8 mm, imagen máximo 96 mm, margen izquierdo 0,5 mm, marca de fin, Chrome normal sin `--kiosk-printing`. Lo fija `tests/test_impresion_parametros_fijos.py`.

## 2. Qué falta

### Marca propia
1. Un lugar donde guardar la marca de la EMPRESA (logo, color, nombre visible, remitente, pie legal).
2. Que cada pantalla y cada correo pregunten «¿de qué empresa es esto?» y usen su marca; hoy preguntan solo por el evento o usan lo global.
3. Que la casilla `own_brand` del plan de verdad permita o impida usar la marca propia.
4. Remitente de correo por empresa (hoy es uno solo, el de Golden).
5. Textos legales por empresa (el aviso de privacidad y el consentimiento facial de una empresa cliente NO pueden ser los de la auditora para Golden; `docs/27` §5 pieza 6). Eso necesita redacción de la auditora y **no son horas de código**.
6. Dominio propio o subdominio por empresa (opcional, etapa final).

### Facturación
1. Tablas de cargos y pagos por empresa.
2. Cálculo mensual del consumo y de los cargos (el Job horario de operaciones `app/ops_runner.py` ya existe y puede hacerlo sin tocar la base con frecuencia).
3. Pantalla «Estado de cuenta» para Golden (en `/plataforma`) y para el administrador de la empresa (solo lectura).
4. Enlace de pago (Wompi) y registro del pago.
5. Suspensión por mora con aviso (la suspensión ya existe en `platform.py`; falta que cierre el ingreso, que es la pieza 3 de `docs/27`).
6. Factura electrónica DIAN: primero manual (la hace el contador en su programa y se adjunta el PDF); integración por API después.

## 3. Tablas y columnas nuevas (diseño exacto)

Todas las migraciones: escritas a mano, aditivas, `revision` ≤ 32 caracteres, con la misma forma defensiva de `0162_organizations.py` (revisar `inspect` antes de crear), sin `SET` de sesión (pooler de Neon), sin llaves foráneas nuevas hacia tablas grandes. La cabeza actual es `0164_accept_verify_photo`; las nuevas serían `0165_org_branding` y `0166_org_billing` (confirmar la cabeza con `alembic heads` antes de numerar).

### 3.1 Migración `0165_org_branding` (marca)
Tabla nueva `org_branding` (una fila por empresa; se separa de `organizations` para no engordar la tabla que lee cada petición):

| Columna | Tipo | Para qué |
|---|---|---|
| `org_id` | Integer, PK | Empresa. |
| `display_name` | String(120) NULL | Nombre que se ve en pantallas y correos (NULL = `organizations.name`). |
| `logo_key` | String(300) NULL | Clave en `app/storage.py` (p. ej. `orgs/<org_id>/logo.png`); NULL = logo por defecto. |
| `logo_version` | Integer, default 1 | Sube al cambiar el logo; va en la URL (`?v=`) para saltar cachés. |
| `brand_color` | String(7) NULL | `#rrggbb`; se valida con `app/brandcolor.validate` (misma regla de contraste). |
| `sender_name` | String(120) NULL | Nombre del remitente de correo. |
| `sender_email` | String(200) NULL | Dirección de respuesta (`Reply-To`) de la empresa. **No** se envía «desde» ella (ver riesgos). |
| `footer_name`, `footer_nit`, `footer_address`, `footer_phone`, `footer_email` | String NULL | Pie legal de los formularios públicos de la empresa (reemplaza lo de `app/legal.py` `info()` solo para sus eventos). |
| `hide_golden_mark` | Boolean, default false | «Marca blanca» (quita «Powered by Golden» si existiera). Solo plan `empresa`. |
| `updated_at`, `updated_by_id` | DateTime, Integer | Auditoría. |

Se guardan también los cambios en `audit_actions` (`app/audit_actions.py`), como ya hace el color de evento.

### 3.2 Migración `0166_org_billing` (cobro)
Tabla `org_subscriptions` (una vigente por empresa):

| Columna | Tipo | Para qué |
|---|---|---|
| `id`, `org_id` (índice) | | |
| `plan` | String(20) | Plan contratado (mismo vocabulario que `organizations.plan`). |
| `price_cop` | Integer | Precio mensual pactado en pesos, sin IVA (permite precios especiales sin tocar `PLANS`). |
| `billing_day` | Integer 1-28 | Día de corte. |
| `trial_ends_at`, `starts_at`, `ends_at` | DateTime NULL | Prueba y vigencia. |
| `status` | String(12) | `trial` / `active` / `past_due` / `suspended` / `cancelled`. |
| `created_at` | DateTime | |

Tabla `org_charges` (un cargo por línea; nunca se borra, solo se anula):

| Columna | Tipo | Para qué |
|---|---|---|
| `id`, `org_id` (índice), `period` (String(7), `2026-12`) | | |
| `kind` | String(20) | `plan` / `extra_attendees` / `local_key` / `service` / `adjustment`. |
| `description` | String(200) | Texto que ve la empresa. |
| `quantity`, `unit_price_cop`, `amount_cop` | Integer | `amount_cop = quantity × unit_price_cop` (guardado, no recalculado). |
| `iva_cop` | Integer | IVA 19 % calculado al crear (decisión 3 de §6). |
| `status` | String(12) | `pending` / `paid` / `void`. |
| `invoice_ref`, `invoice_file_key` | String NULL | Número de la factura electrónica y PDF adjunto (manual al inicio). |
| `created_at`, `paid_at` | DateTime | |
| Único (`org_id`, `period`, `kind`, `description`) | | El Job puede correr dos veces sin duplicar cargos. |

Tabla `org_payments`: `id`, `org_id`, `charge_id` NULL, `amount_cop`, `method` (`wompi` / `transferencia` / `manual`), `wompi_reference` NULL, `received_at`, `registered_by_id`, `note`. El pago por Wompi reutiliza `app/wompi.py` y la cuenta de Golden (la de `wompi.config()`), no las de terceros.

No se crea tabla de «planes» (siguen en `app/orgs.py` `PLANS`; `docs/27` §5 ya decidió separarlos solo cuando haga falta historial).

## 4. Orden de pasos con horas estimadas

Total estimado: **marca 40-56 h, facturación 40-56 h** (más 16 h si se hace subdominio y 40 h+ si se integra la factura electrónica por API). Cada paso termina con su commit + push y sus pruebas de texto en verde (`python3 -m pytest --noconftest -q tests/<archivo>.py`, `ruff check .`). La suite completa de GitHub corre UNA vez al final (flujo INAMOVIBLE, `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md` §3).

### Bloque A · Marca propia
| # | Paso | Detalle exacto | Horas |
|---|---|---|---|
| A1 | Migración `0165_org_branding` + modelo `OrgBranding` | §3.1. Prueba de migración en la suite con base (la hará la corrida final). | 3 |
| A2 | Módulo nuevo `app/org_brand.py` | Funciones puras y con caché corta (`app/ttlcache.py`, 30 s, como `logosize`): `for_org(db, org)`, `for_event(db, event)` (sube del evento → cliente → empresa), `display_name`, `logo_url`, `css`, `sender`. Regla de herencia: **evento (si lo personalizó) > empresa > Golden**. Golden y las empresas sin fila devuelven lo de hoy, sin consultar la base. | 6 |
| A3 | API y pantalla «Marca» | Rutas `GET/PUT /api/org/brand` y `POST /api/org/brand/logo` (admin de la empresa) y la misma desde `/plataforma` para Golden. Subida con `app/storage.py` (nunca `open()` sobre `data/`), mismas extensiones que el logo de evento (sin SVG: `LOGO_EXT` en `parametros.py`), vista previa antes de guardar, botón «Restaurar el de Golden», ayuda ⓘ completa (principio «dummy»). Solo con `orgs.entitlement(org, "own_brand")` verdadero; si no, mensaje «Tu plan no incluye marca propia; contacta a soporte». Ruta pública del logo `/branding/<org_id>/logo?v=<logo_version>` (diseño ya anotado en `docs/16` §7b; debe ir al servicio correcto en `app/appmode.py` y en las reglas de Firebase, `deploy/firebase/make_config.py`). | 10-14 |
| A4 | Aplicar la marca en las páginas | `event_logo_url`/`event_logo_attrs` (`app/main.py`) pasan a pedir `org_brand.for_event`; `brandcolor.css(...)` recibe el color ya resuelto; `login.html`, `_legal_footer.html` y las plantillas con «Golden» fijo usan `display_name` (empezar por las públicas: formulario `/f/*`, aceptación, certificado, escarapela digital, estadísticas TV; el panel interno después). Con las opciones apagadas el resultado debe ser idéntico al de hoy. | 8-12 |
| A5 | Correos | `app/mailer.py`: parámetro opcional `from_name` y `reply_to` por empresa; **el remitente real sigue siendo el de Golden** (nombre visible «Empresa X vía GoldenWeb», `Reply-To` la dirección de la empresa). Textos de `staff_credentials.py`, `notifications.py`, `event_report.py`: «Golden…» → `display_name`. `wallet.py`: `BRAND` por empresa. `report_book.py`: marca del pie según `hide_golden_mark`. | 6-8 |
| A6 | Pruebas | Puras: herencia evento > empresa > Golden, contraste, extensión de logo, plan sin `own_brand`, Golden idéntico a hoy. Con base: dos empresas no ven la marca de la otra (en la corrida final). Visual: revisar ancho por ancho (320-3440 px) con `scripts/visual_harness` como exige `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md` §6. | 6-8 |
| A7 | (Opcional, etapa final) Dominio propio por empresa | Ver §5, riesgo 6. Subdominio `empresa.app.golden-eventos.com` (sin costo) o dominio del cliente. | 16 |

### Bloque B · Facturación
| # | Paso | Detalle exacto | Horas |
|---|---|---|---|
| B1 | Migración `0166_org_billing` + modelos | §3.2. | 4 |
| B2 | Módulo `app/org_billing.py` (lógica pura + consultas) | `price_for(org, period)`, `usage_for_period(db, org, period)` (reutiliza `orgs.usage`, pero con ventana del mes pedido y asistentes de ese mes), `generate_charges(db, period)` (idempotente por el índice único), IVA 19 %, excedentes por asistente según la tabla aprobada. Los precios salen de `org_subscriptions.price_cop`, no del código. | 10-14 |
| B3 | Paso mensual en el Job de operaciones | Nuevo paso en `app/ops_runner.py` que llama `generate_charges` una vez al mes, registrado en `audit_actions`. Nada que toque la base con frecuencia (regla de costo de Neon). | 3 |
| B4 | Pantalla «Estado de cuenta» | En `/plataforma` (Golden): cargos, pagos, saldo, botón «Registrar pago», «Anular cargo» (con confirmación), «Adjuntar factura (PDF)». Para el administrador de la empresa: solo lectura de lo suyo. Con `showToast`/`showConfirm`, tokens `--gw-*`. | 12-16 |
| B5 | Enlace de pago Wompi | Reutilizar `app/wompi.py` con la cuenta de Golden; webhook propio (ruta nueva, mismo patrón que `/webhooks/wompi/<ref>`) que marca el cargo `paid`. Probar primero en modo pruebas de Wompi. | 8-12 |
| B6 | Mora y suspensión | Aviso por correo a 5 días del vencimiento y al vencer; pasar la suscripción a `past_due` y, si Juan David lo decide, a `suspended` (reutiliza `orgs.check_limit`, que ya responde `SUSPENDED_MESSAGE`). **Depende de la pieza 3 de `docs/27`** (cerrar el ingreso de empresas suspendidas, 20-30 h, no incluidas aquí). | 3-5 |
| B7 | Factura electrónica | Etapa 1 (incluida): campo `invoice_ref` + PDF adjunto; el contador factura en su programa. Etapa 2 (NO incluida, 40+ h): integración por API con el proveedor que Juan David elija. | 0 / 40+ |

## 5. Riesgos y cómo evitarlos

1. **Romper la impresión INAMOVIBLE (el más grave).** Regla: ningún paso de este plan toca `templates/badge_print.html`, `static/js/badge-render.js`, `static/js/label-compose.js`, `static/js/shared-print.js`, `templates/impresion_usb.html` ni los parámetros de página. La marca de empresa NO se aplica dentro de la escarapela (la escarapela es el diseño del cliente por evento; su logo ya es suyo). Lo único permitido es que el diseñador de escarapela ofrezca el logo de la empresa como imagen que el cliente puede arrastrar: eso entra como un elemento más del diseño y la impresión no cambia. Antes de cada commit: correr `python3 -m pytest --noconftest -q tests/test_impresion_parametros_fijos.py tests/test_impresion_compartida.py tests/test_ajustes_impresion.py` (deben seguir en verde sin editarlos). Si alguna vez hace falta tocar impresión, solo con orden expresa de Juan David y repitiendo la prueba física en la Brother QL-800.
2. **Marca en correos y entregabilidad.** Enviar «desde» el dominio de otra empresa sin autenticarlo (SPF/DKIM) manda los correos a spam o permite suplantación. Por eso el plan envía SIEMPRE desde el remitente de Golden y solo cambia el nombre visible y el `Reply-To`. Enviar con dominio propio de la empresa exige que ella configure DNS y que Golden use un servicio de correo por dominio: queda fuera de este plan y se decide en §6 (pregunta 5).
3. **Textos legales por empresa.** Cambiar el nombre de Golden por el de la empresa en el aviso de privacidad o el consentimiento facial NO es una cuestión de marca: son textos LITERALES de la auditora (`app/legal_texts_data.py`, no se editan) y el Responsable del tratamiento cambia. Regla: la marca solo toca el encabezado, el color y el pie de contacto; el reconocimiento facial de una empresa distinta de Golden sigue bloqueado hasta que la auditora entregue sus textos (`docs/27` §5, pieza 6; `app/acceptmail.py` ya se limita a eventos de Golden por esto).
4. **Logos subidos por terceros.** Sin SVG (un SVG puede llevar scripts); límite de tamaño y de dimensiones; se sirve con `X-Content-Type-Options: nosniff` (ya lo pone `app/main.py`). La ruta pública `/branding/...` no debe revelar la existencia de otras empresas (usar el número de empresa solo para su propio logo; no listar).
5. **Colores ilegibles.** Reutilizar `brandcolor.validate` (rechaza color sin contraste AA). No inventar otra validación.
6. **Dominio propio / subdominio.** Cada dominio nuevo exige: registro DNS (lo crea Juan David, nunca Claude: regla de §2 de `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`), dominio personalizado en Firebase Hosting, y que la CSRF por Origen (`app/main.py` 144-163) y `PUBLIC_BASE_URL` acepten ese host por empresa. Las cookies de sesión (`__session`) son por host: no se cruzan entre empresas. Por costo y complejidad se deja como último paso opcional.
7. **Cobro sin aislamiento entre empresas.** El estado de cuenta de una empresa nunca debe ser visible para otra. Mientras `ENFORCE_STAFF_TENANT=0`, la app se niega a crear administradores de empresas externas (`orgs.external_accounts_ready`), así que la facturación a una empresa real **no puede salir antes** de encender el aislamiento en staging y pasar la prueba de dos empresas (`docs/27` §2).
8. **Dinero.** Tope de infraestructura US$40/mes (INAMOVIBLE): el Job mensual y la caché de marca no agregan consultas frecuentes; la ruta del logo usa caché pública con versión. Nada de servicios de pago nuevos sin avisar.
9. **Datos personales.** El estado de cuenta muestra cifras agregadas (conteos), nunca listas de personas. Nada de cédulas ni nombres en logs ni en los PDF de factura.
10. **Cifras de precio.** Los planes de `PLANS` y la propuesta financiera son un punto de partida, no precios; el cobro leerá `price_cop` de la suscripción para no incrustar precios en el código.

## 6. Qué decide Juan David

Cada pregunta trae opciones y una recomendación.

1. **¿Qué se construye primero?**
   a) Marca propia primero; b) Facturación primero; c) Ambas en paralelo.
   **Recomendación: (a).** Es lo primero que pide un cliente al mirar la plataforma, y la facturación al inicio se puede hacer a mano (estado de cuenta en Excel y factura del contador) con los primeros 1 o 2 clientes sin perder dinero.
2. **¿La marca propia es un cambio de aspecto o también «marca blanca» total?**
   a) Solo logo, color y nombre (con «hecho con GoldenWeb» discreto); b) Además quitar toda mención de Golden (plan Empresa).
   **Recomendación: (a) en Básico y Pro; (b) solo en Empresa y a un precio mayor.**
3. **IVA y moneda de los cargos.** a) Precios en pesos + IVA 19 % (como la propuesta); b) Precio con IVA incluido.
   **Recomendación: (a).** Es lo que dice la propuesta y lo que espera una empresa que retiene en la fuente.
4. **¿Cuánto cobra Golden por la marca propia?** a) Incluida en Pro y Empresa (como hoy dice `PLANS`); b) Adicional.
   **Recomendación: (a)** hasta tener dos clientes; revisar después.
5. **Remitente de los correos.** a) Siempre desde Golden con nombre visible y «responder a» de la empresa; b) Desde el dominio de la empresa (ella configura DNS y Golden contrata un servicio de correo por dominio).
   **Recomendación: (a).** (b) es una pieza aparte con costo y soporte.
6. **Dominio.** a) Ninguno (todas entran por `app.golden-eventos.com`); b) Subdominio `empresa.app.golden-eventos.com` (solo Empresa); c) Dominio del cliente.
   **Recomendación: (a) ahora, (b) cuando un cliente lo pida.** Cada paso de DNS lo ejecuta Juan David.
7. **¿Cómo se paga?** a) Transferencia y registro manual del pago; b) Enlace de pago Wompi con la cuenta de Golden; c) Cobro automático recurrente.
   **Recomendación: (b)** con (a) como respaldo; (c) no, por riesgo y por la regla de «sin compromisos anuales».
8. **Factura electrónica DIAN.** a) Manual: la hace el contador y se adjunta el PDF; b) Integración por API con un proveedor.
   **Recomendación: (a)** hasta tener 5 clientes; (b) después. Hay que preguntarle al contador qué proveedor usa hoy.
9. **Mora.** ¿A los cuántos días de atraso se suspende la empresa y se le cierra el ingreso? a) 5 días; b) 15 días; c) Nunca automático, lo decide Golden.
   **Recomendación: (b)** con aviso a los 5 y a los 10 días, y suspensión que solo bloquea crear cosas nuevas y deja ver y exportar lo suyo (no se le retienen sus datos).
10. **Primer evento gratis y periodo de prueba.** La propuesta financiera dice «primer evento gratis hasta 200 asistentes». ¿Se implementa como `trial` de la suscripción?
    **Recomendación: sí**, con un tope de 14 días y 200 asistentes, para que la prueba no se vuelva cobro regalado.
11. **Textos legales de empresas clientes.** ¿Se encarga ya a la auditora la redacción del aviso y del consentimiento facial para empresas distintas de Golden, o se vende primero SIN reconocimiento facial?
    **Recomendación: vender primero sin reconocimiento facial** (plan Básico no lo incluye hoy) y pedir los textos a la auditora en paralelo.
12. **Precios.** ¿Se mantienen los de la propuesta (Evento suelto COP 390.000, Pro COP 990.000/mes, Empresa COP 2.490.000/mes) o cambian? El código leerá lo que él decida de `price_cop`.
    **Recomendación: no fijar nada hasta tener el primer cliente real;** la propuesta dice que subir precios después es más difícil que bajarlos, por lo que conviene arrancar en la propuesta y revisar a los 3 meses.

## 7. Qué no pude comprobar

- No ejecuté nada: ni pruebas con base de datos, ni migraciones con Alembic real, ni la pantalla `/plataforma` en un navegador. Todo lo afirmado sale de leer el código con `grep` y rangos de líneas.
- No comprobé en vivo que Firebase Hosting deje pasar la ruta nueva `/branding/**` hasta que se ajuste `deploy/firebase/make_config.py`; es un cambio por hacer, no verificado.
- No verifiqué que `own_brand` no se use en `static/js/plataforma.js` más allá de mostrar la casilla (las búsquedas en `static/` y `templates/` no devolvieron resultados; es lectura, no ejecución).
- No sé cuántas de las 61 plantillas con «Golden» son texto visible para empresas externas y cuántas son solo internas (no las abrí una por una); el paso A4 debe empezar con ese inventario.
- No conozco el proveedor de factura electrónica ni el programa contable del contador de Golden.
- Las horas son estimaciones mías a partir de piezas parecidas ya hechas (`docs/revision_2026-11-22/07`, S5/S6); no hay medición.
- No comprobé qué retenciones aplican a cada cliente ni el tratamiento tributario exacto del cobro; eso es del contador.
