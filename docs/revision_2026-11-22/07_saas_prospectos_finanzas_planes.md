# 07 · GoldenWeb 2.0 como SaaS: prospectos, finanzas y planes (revisión 22-nov-2026)

**Rol del agente:** cinco voces en pasadas separadas (gerente de ingeniería de un prospecto, CFO del prospecto, asesor financiero interno de Golden, asesor financiero externo, presidente), crítica cruzada a ciegas y propuesta final. **No se cambió código.** Todo lo de dinero son **estimaciones con supuestos escritos**; los precios de la competencia son de memoria (2024-2025) y hay que verificarlos antes de usarlos en una propuesta comercial.

Fuentes leídas: `docs/13_ARQUITECTURA_ESCALABILIDAD.md` §6, `docs/16_BACKLOG_PRODUCTO.md`, `docs/00_README.md`, `docs/01_VISION_Y_ALCANCE.md`, `docs/23_COBROS_WOMPI_MULTICUENTA.md`, `docs/20_CUENTAS_POR_SERVICIO.md`, `docs/17_SERVIDOR_LOCAL.md`, `docs/18_EXPORTAR_EVENTOS.md`, `docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`, `app/auth.py`, `app/models.py` (Tenant, StaffUser, Event, InfraCost, EventExpense, LocalServerKey, PaymentAccount), `app/server_keys.py`, `app/infra_costs.py`, `app/routers/gastos.py`, `app/routers/gastos_eventos.py`, `app/routers/tenants.py`, `app/main.py` (logo), y `/home/claude/golden-sitio-web/src/data/inicio.json`.

---

## 1. Resumen en 5 líneas
1. **Técnicamente la plataforma está mucho más cerca del SaaS de lo que parece**: hay aislamiento por cliente (`ENFORCE_STAFF_TENANT`, apagado), llaves de producto, cuentas de cobro por tercero, exportación completa de eventos y panel de costos de infraestructura con reparto por evento. Lo que falta es la **capa comercial**: cuenta/empresa suscriptora, planes y límites en la base, alta sin código, estado de cuenta, marca propia por empresa y borrado/exportación de TODO lo de una empresa.
2. **Lo más grave:** hoy `Tenant` significa «cliente de Golden», no «empresa que compra el software». Una empresa de eventos que contrate el SaaS tiene SUS propios clientes; ese nivel (cuenta suscriptora → sus clientes → sus eventos) **no existe** y es la pieza que ordena todo lo demás (~40-60 h).
3. **Lo más valioso:** el costo de infraestructura es despreciable (tope US$40/mes ≈ COP 160.000 para TODOS los clientes): un solo cliente en plan mensual paga la nube entera. El margen bruto por plan supera el 70 %; el costo real está en **soporte en noches de evento** y en el **mantenimiento del software**, no en servidores.
4. **Precio propuesto (presidente):** cuatro escalones: *Evento suelto* COP 390.000 (≈US$95), *Pro* COP 990.000/mes (≈US$240), *Empresa* COP 2.490.000/mes (≈US$600) y *Golden opera tu evento* desde COP 12.000 por asistente (mínimo COP 1.800.000). Todo + IVA 19 %.
5. **Riesgos reales:** poner el precio tan bajo que no pague un turno de soporte nocturno; que el SaaS le quite eventos operados a Golden (margen mucho mayor); el **repositorio es público sin archivo de licencia** (cualquiera puede leer y correr el código); y la biometría exige que CADA empresa suscriptora tenga sus propios textos legales (los actuales son de la auditora PARA Golden).

---

## 2. Hallazgos

| # | Severidad | Qué pasa | Dónde | Por qué importa | Qué se hizo |
|---|---|---|---|---|---|
| 1 | **Crítica** | No existe el nivel «empresa suscriptora». `Tenant` = cliente final de Golden; `StaffUser.tenant_id` nulo = global (Golden). Una empresa SaaS necesita tener VARIOS clientes finales. | `app/models.py` (Tenant, StaffUser, Event); `app/auth.py` `assert_event_tenant` | Sin esto no hay planes, límites, facturación ni aislamiento «por empresa»; solo «por cliente final». | Propuesto (§4, pieza S1) |
| 2 | **Crítica** | El aislamiento por cliente está construido pero **apagado** (`ENFORCE_STAFF_TENANT=0`, `ENFORCE_STAFF_EVENT_SCOPE=0`) y nunca se probó con dos clientes en staging (requisito escrito en `docs/0C_cierre.md`). | `app/auth.py` líneas 239-294; `docs/0C_cierre.md` | Un prospecto preguntará «¿mi gente puede ver eventos de otra empresa?». Hoy la respuesta honesta es «el código lo impide si se enciende el interruptor; no se ha probado». | Pendiente |
| 3 | **Alta** | Repositorio **público y sin archivo `LICENSE`**. | raíz del repo | Un competidor puede leer el código, copiar funciones o montarlo por su cuenta (con esfuerzo). Vender SaaS con el código a la vista reduce la ventaja a: datos, soporte, marca, operación y velocidad. | Propuesto: decidir licencia o pasar a privado (decisión de Juan David, no técnica) |
| 4 | **Alta** | Los textos legales de biometría son LITERALES de la auditora para Golden como responsable del tratamiento. Una empresa suscriptora sería **responsable** y Golden **encargado**; sus avisos de privacidad y consentimientos tendrían que ser suyos. | `app/legal_texts_data.py`, `app/legal.py`, `/privacidad`, `/terminos` | Vender reconocimiento facial a terceros sin resolver esto es un riesgo legal (Ley 1581) para Golden y para el cliente. | Pendiente (requiere auditora, no código) |
| 5 | **Alta** | No hay planes, límites ni contadores por empresa (eventos/mes, asistentes, usuarios, funciones). Los interruptores existen solo **por evento** (`facial_enabled`, `inventory_enabled`, `areas_enabled`…). | `app/models.py` Event; `AppSetting` | Sin límites en la base, cualquier plan es «de palabra». No se puede cobrar por consumo ni cortar al que no paga. | Propuesto (S3) |
| 6 | **Alta** | No hay «estado de cuenta» ni factura dentro de la app. Lo que existe: `PaymentAccount` (cobros Wompi de terceros) y *Payment Links*, pensados para formularios, no para cobrar la suscripción. | `app/routers/payment_accounts.py`, `docs/23` | El CFO del prospecto quiere factura electrónica DIAN, IVA discriminado y pago en COP. | Propuesto (S5; facturación electrónica por el contador al principio) |
| 7 | **Media** | Exportar/borrar «todo lo de mi empresa» no existe como una sola acción: exportar es por evento y **solo super_admin** (`event_transfer`); borrar un cliente exige archivarlo y que no tenga eventos (`delete_tenant`). | `app/routers/event_transfer.py`, `app/routers/tenants.py` 183-197 | «¿Me llevo mis datos si me voy?» es la primera pregunta de un gerente de ingeniería. Hoy: sí, pero lo hace Golden a mano, evento por evento. | Propuesto (S7) |
| 8 | **Media** | Marca propia: el logo es por evento (`logo_mode custom`) o por variable de entorno global (`DEFAULT_LOGO_URL`). No hay logo/colores/remitente de correo **por empresa**; el correo sale por la cuenta Microsoft de Golden. | `app/main.py` 318-338, `Event.logo_*` | El prospecto quiere que sus clientes vean SU marca en escarapela digital, formularios y correos, no la de Golden. | Propuesto (S6) |
| 9 | **Media** | Soporte dentro de la app: hay notificaciones internas, alertas de sistema por correo y solicitudes de privacidad; no hay «pedir ayuda», historial de tickets ni página de estado pública. | `app/routers/notifications.py`, `system_alerts.py`, `privacy_requests.py` | A las 7 pm de un evento ajeno, el cliente necesita un canal y un compromiso de respuesta; hoy sería el WhatsApp de Juan David. | Propuesto (S9) |
| 10 | **Media** | El costo por evento YA se mide (reparto de infraestructura por actividad y días activos; legalizaciones con digitadores, hospedaje, pasajes, alimentación) pero no hay **costo de personal y equipos por evento operado** consolidado ni «margen por evento». | `app/infra_costs.py`, `EventExpense` (`kind`), `gastos_eventos.py` | Para fijar la tarifa por asistente de «Golden opera», hace falta el número real; hoy sale de sumar dos pantallas a mano. | Pendiente (reporte, 8-12 h) |
| 11 | **Media** | Módulos internos de Golden mezclados con lo vendible: CRM (decisión 22-nov: NO va en el SaaS), legalizaciones, almacén/inventario de bodega, asignación de coordinadores, gastos de infraestructura. | `app/routers/crm*.py`, `legalizations.py`, `almacen*.py`, `coord_assign.py`, `gastos.py` | Una empresa suscriptora no debe ver ni la barra lateral con esas pantallas. Hace falta un interruptor «cuenta interna de Golden» vs «cuenta SaaS». | Propuesto (S2) |
| 12 | **Baja** | El sitio web (`inicio.json`) promete «Registro y acreditación… con tecnología propia», rostro voluntario, aforo en vivo y cotización por evento: **no promete SaaS**. Bien: no hay deuda de promesa. Pero tampoco hay una puerta de entrada para «quiero el software». | `golden-sitio-web/src/data/inicio.json` | Si se decide vender SaaS, el sitio necesita una sección «GoldenWeb para empresas de eventos» con planes y un formulario de contacto. | Pendiente (sitio, otra sesión) |
| 13 | **Baja** | Neon plan Launch no trae SLA contractual (`docs/13` §5); Cloud Run sí (99,95 %). El modo contingencia y respaldos lo compensan. | `docs/13` | Un SLA prometido al cliente debe ser menor que el más débil de los proveedores: ofrecer 99,5 % mensual medido en `/health`, con crédito, no reembolso. | Propuesto (contrato) |

---

### 2.1 Las cinco pasadas (cada una escrita sin ver las otras)

#### Pasada 1 · Gerente de ingeniería de «Eventos del Caribe S.A.S.» (empresa mediana colombiana, ~25 eventos/año, evalúa contratar GoldenWeb como SaaS)

Lo que necesito ver antes de firmar, en orden:
1. **Aislamiento de mis datos.** Que mi gente solo vea mis clientes y mis eventos, y que lo pueda demostrar: una cuenta mía intentando abrir un evento ajeno recibe 404. Leí `app/auth.py`: la regla existe (`assert_event_tenant`, `scope_events_query`) pero depende de una variable de entorno que hoy está en 0. Quiero verla encendida y una prueba automática que lo compruebe con dos empresas.
2. **Quién es «responsable» de los datos.** Mis asistentes son mis datos; Golden es mi encargado. Necesito un contrato de encargo (Ley 1581, art. 25 Decreto 1377/2013) y poder cargar MI aviso de privacidad y MI texto de consentimiento facial. Hoy los textos son de Golden y no se editan.
3. **Exportar y borrar.** Un botón «descargar todo lo de mi empresa» (eventos, personas, registros, respuestas de formularios, pagos; sin vectores faciales) y «cerrar cuenta» con borrado comprobable a los 30 días. Hoy la exportación completa de un evento existe (`docs/18`), pero solo la hace un super_admin de Golden.
4. **Marca propia.** Mi logo en escarapela digital, formularios públicos, correos y la pantalla de ingreso de mis digitadores; un subdominio `eventos.micaribe.com` sería el ideal, un `micaribe.app.golden-eventos.com` me sirve para empezar. Hoy el logo es por evento.
5. **Integraciones.** Como mínimo: exportación CSV/XLSX (existe), webhook o correo al registrar (parcial), y pagos con MI cuenta Wompi (existe: `docs/23`, llaves cifradas, webhook por cuenta: esto es un punto muy fuerte).
6. **SLA y soporte.** Disponibilidad mensual publicada, una página de estado, un canal con hora de respuesta: 15 min en evento, 1 día hábil fuera de evento. Quiero saber quién contesta a las 8 pm un sábado.
7. **Onboarding sin tocar código.** Que yo mismo cree mi empresa, mi primer administrador, mis clientes, mis eventos, mis plantillas de escarapela y mis formularios. Hoy el primer administrador se crea con `scripts/create_staff_user.py` (línea de comandos): eso no es SaaS.
8. **Servidor local.** Que pueda instalar el servidor en mi portátil con una llave que yo mismo genero (existe: `app/server_keys.py`, `GLD-XXXX-XXXX-XXXX`, un solo uso, se deshabilita desde la nube). Me gusta: es serio.
9. **Impresoras.** Trabajo con Brother QL-800 también; que la impresión desde celular Android (WebUSB) venga documentada y probada. `docs/16` dice que el prototipo está y falta la prueba con la impresora real integrada al registro.
10. **Código público.** Lo vi en GitHub. Me da confianza (puedo auditarlo) y a la vez me pregunto por qué pagaría si podría montarlo. Respuesta que me convencería: «porque operarlo, soportarlo y mantenerlo al día no es lo que usted hace».

**Veredicto del gerente:** firmaría un piloto de 2-3 eventos si (1), (2), (3) y (7) existen. Sin (1) ni (7) no paso de la demostración.

#### Pasada 2 · Contador/CFO de la misma empresa

- **Moneda y facturación.** Pago en COP, factura electrónica DIAN con IVA 19 % discriminado (el software como servicio es gravado), retención en la fuente por servicios si aplica (mi empresa es agente retenedor; Golden debe estar lista para que le retengan el 4 % o el 11 % según el concepto que pongan en la factura; que el contrato diga «licencia de uso de software/servicio» claramente). Si Golden factura en USD me complica: pago en COP a la TRM del día y necesito que la factura esté en pesos.
- **Modelo de cobro.** Comparo tres: (a) por evento: me gusta porque lo cargo al centro de costos del evento y se lo traslado al cliente final; (b) plan mensual: me sirve si hago ≥ 2 eventos al mes, si no, pago meses vacíos; (c) por asistente: es lo más justo, pero impredecible y me obliga a auditar el conteo. **Lo que pediría:** plan mensual con eventos incluidos y **excedente por asistente** a precio conocido, o pago por evento para empezar sin compromiso.
- **Cuánto pagaría.** Mi referencia es lo que me cuesta hoy: Excel + un sistema viejo + 2 personas una tarde cuadrando listas. Si el software me ahorra 1 digitador por evento (≈ COP 120.000-150.000 por jornada) y 4 horas de oficina (≈ COP 100.000), vale **COP 250.000-400.000 por evento** sin pensarlo. Un plan mensual de **COP 800.000-1.200.000** lo justifico a partir de 3 eventos/mes. Por encima de COP 2.500.000/mes necesito que incluya algo que hoy pago aparte (servidor local, soporte en el evento, impresión).
- **Justificación interna.** Es gasto operativo trasladable (lo cotizo dentro del evento al cliente final con margen). Si el precio es por evento, se traslada 1:1; si es plan mensual, lo prorrateo.
- **Lo que no acepto:** cobro por usuario (mis digitadores son temporales), compromisos anuales el primer año, precios en USD en la factura, cobro de comisión sobre MIS pagos de inscripción (si uso mi Wompi, Wompi ya me cobra su comisión).
- **Prueba:** un mes gratis o el primer evento gratis, con mis datos reales exportables al salir.

#### Pasada 3 · Asesor financiero interno de Golden (conoce la casa)

**Supuestos explícitos (cambiarlos cambia todo):**
- TRM de trabajo **COP 4.000 por US$1** (el panel de Gastos guarda la TRM real del día en `infra_costs.trm`; aquí se redondea).
- Infraestructura nube: **US$22-35 típico, tope US$40** (`docs/13` §6) = **COP 88.000-160.000/mes** para TODA la plataforma, no por cliente.
- Golden hace ~**12 eventos/mes** (del supuesto de `docs/13` §6: «2 noches pesadas + 10 normales»). Evento «típico» de referencia: **500 asistentes, 1 día, Bogotá**.
- Jornal de digitador **COP 120.000-150.000** (`EventExpense.kind='digitador'` existe para medirlo de verdad); coordinador **COP 200.000-250.000/día**; 1 digitador por cada **100-150 asistentes** en hora pico (con cédula/QR; con facial la fila es más lenta en la primera visita).
- Brother QL-800: **~COP 1.000.000** el equipo (se amortiza en ~50 eventos = COP 20.000/evento); rollo continuo 62 mm DK-22205 ≈ **COP 70.000-90.000** por 30,48 m → etiqueta de 99,8 mm ≈ 300 por rollo ≈ **COP 250-300 por escarapela** impresa.
- Tableta/celular Android y lector de cédula: amortización **COP 10.000-15.000/evento**. Router y portátil servidor local: **COP 10.000/evento**.
- Mantenimiento del software: **40 h/mes** de desarrollo/soporte a COP 80.000/h = **COP 3.200.000/mes** (lo que hoy hace Juan David con Claude; es un costo de oportunidad real aunque no se pague a terceros).
- Soporte en noche de evento: **2 h × COP 60.000 = COP 120.000** por evento.

**(a) Costo real por evento, SOLO software (lo que le cuesta a Golden que un tercero use la plataforma un evento más):**

| Concepto | Cálculo | COP/evento |
|---|---|---|
| Nube, parte fija prorrateada | COP 140.000 ÷ 12 eventos | ~12.000 |
| Nube, marginal del evento (Cloud Run en la ventana, ~3 CU-h de Neon, fotos en Storage) | US$1-3 | 4.000-12.000 |
| Mantenimiento del software prorrateado | COP 3.200.000 ÷ 12 | ~270.000 |
| Soporte de la noche del evento | 2 h | ~120.000 |
| **Total software solo** | | **≈ COP 400.000-415.000 (≈ US$100)** |
| **Marginal puro** (si el mantenimiento ya está pagado por Golden mismo) | nube + soporte | **≈ COP 125.000-135.000 (≈ US$32)** |

Lectura: el costo que de verdad crece con cada cliente nuevo es el **soporte** (COP 120.000) y no la nube (COP 4.000-12.000). Por eso un plan sin soporte nocturno puede costar poco y uno con soporte nocturno no puede.

**(a-bis) Costo real por evento OPERADO por Golden (500 asistentes, 1 día, Bogotá):**

| Concepto | Cálculo | COP/evento |
|---|---|---|
| Software (fila anterior, total) | | 400.000 |
| 4 digitadores | 4 × 135.000 | 540.000 |
| 1 coordinador | 1 día | 225.000 |
| Escarapelas impresas | 500 × 275 + 20.000 amortización QL-800 | ~160.000 |
| Tabletas, lector, router, portátil | amortización | ~25.000 |
| Transporte local y alimentación del equipo | legalización típica | ~150.000 |
| Imprevistos (10 %) | | ~150.000 |
| **Total operado, Bogotá** | | **≈ COP 1.650.000 (≈ US$410) → COP 3.300 por asistente** |
| Fuera de Bogotá | + pasajes, hospedaje, viáticos (`EventExpense.kind` hospedaje/pasaje) | + COP 600.000-1.500.000 |

Con 200 asistentes el costo operado baja a ~COP 900.000 (COP 4.500/asistente: el fijo pesa más); con 2.000 sube a ~COP 4.500.000 (COP 2.250/asistente).

**Conclusión interna:** cualquier precio por encima de **COP 450.000 por evento** para software solo deja margen positivo con todo cargado; por encima de **COP 150.000** cubre lo marginal. Para «Golden opera», el precio por asistente debe estar en **3-4 veces** el costo (COP 10.000-14.000) porque el evento operado carga además la venta, el riesgo de cancelación y las noches.

**Lo que ya mide la app y sirve para no adivinar:** `infra_costs` (importación de Google, reparto por actividad/días), `EventExpense` con tipos (digitador, hospedaje, pasajes, taxis, alimentación), panel «Gastos › Eventos» (satisfacción, tiempos, alertas, exportar XLSX). Falta la fila «margen por evento» (ingreso del evento − software − personal − equipos).

#### Pasada 4 · Asesor financiero externo (no conoce a Golden)

Referencias de la industria **(estimadas, de memoria, 2024-2025; verificar antes de citarlas en una propuesta)**:

| Plataforma | Modelo | Precio aproximado | Nota |
|---|---|---|---|
| Eventbrite (global) | por boleta vendida | ~3,7 % + US$1,79 por boleta pagada (EE. UU., 2024); gratis si el evento es gratis; «Pro» para organizadores ~US$15-100/mes | Es venta de boletas, no acreditación; no imprime escarapelas en sitio sin terceros |
| RegFox / Webconnex (EE. UU.) | por registro | ~US$0,99 + 1 % por registro pagado (2024) | Formularios muy buenos; sin puerta |
| Cvent | licencia anual empresarial | desde ~US$10.000-20.000/año y por registro adicional (estimado) | Corporativo grande; incluye check-in e impresión en sitio con hardware alquilado |
| Bizzabo | licencia anual | ~US$15.000-25.000/año (estimado) | Corporativo; onsite con quioscos y «smart badges» |
| Whova | por evento | ~US$1.000-5.000 por evento según asistentes (estimado) | App del asistente; check-in incluido |
| Hopin | — | vendió su negocio de eventos (2023); ya no es referencia | — |
| Swapcard | freemium + por evento | gratis básico; ~US$2.000-10.000 por evento/paquete (estimado) | Ferias y networking |
| Eventtia (Medellín, Colombia) | plan anual por asistentes | ~US$3.000-8.000/año (estimado); vende también onsite | **Competidor directo local**; factura en Colombia |
| Welcu (Chile/LatAm) | comisión por boleta + planes | ~5-8 % por boleta (estimado); planes para corporativos | Fuerte en Chile/Perú |

Lo que se ve en el mercado:
- **Nadie cobra «por usuario»** en eventos; se cobra por registro/boleta (ticketing) o por evento/año (corporativo).
- **El check-in en sitio e impresión** casi siempre es un *add-on* u onsite services que vale más que el software (Cvent/Bizzabo cobran personal y hardware por día).
- **El reconocimiento facial** lo ofrecen pocos (Zenus, Fielddrive) y como premium: **US$1.000-3.000 por evento** o por quiosco/día (estimado).
- **Punto ciego de los globales en Colombia:** factura electrónica DIAN, pago en COP, servidor sin internet y cédula colombiana (PDF417/MRZ). Eso es lo que Golden tiene y ellos no.

Posicionamiento sugerido: **«el Eventtia que además opera la puerta sin internet, imprime en Brother y te cobra en pesos»**. Precio de entrada por evento **US$80-150** (muy por debajo de Whova/Swapcard), plan mensual **US$200-600** y «operado» por asistente. No competir en ticketing con Eventbrite (comisión por boleta): en GoldenWeb el pago entra a la cuenta Wompi del cliente sin comisión de Golden: ese es un argumento de venta, no una fuente de ingreso.

#### Pasada 5 · Presidente (propuesta final): ver §2.3.

### 2.2 Crítica cruzada a ciegas (cada voz lee a las otras por primera vez)

- **Gerente → CFO:** «Pagar por evento te conviene, pero vas a pedir soporte en cada evento como si fuera plan mensual. El soporte nocturno debe estar en el plan mensual, no en el evento suelto.» **Aceptado por el presidente.**
- **CFO → Interno:** «Tu costo de mantenimiento (COP 3,2 M/mes) lo pagas tengas 0 o 20 clientes: no lo cargues por evento; es el umbral de clientes para que el SaaS se pague solo: con un margen de ~COP 700.000 por cliente Pro, **5 clientes Pro cubren el mantenimiento**.» **Aceptado:** el punto de equilibrio son 5 clientes Pro o 2 Empresa.
- **Interno → Externo:** «Comparar con Cvent/Bizzabo infla las expectativas; el prospecto colombiano mediano compara con Excel y con el software viejo. El ancla real es el jornal de un digitador (COP 135.000).» **Aceptado:** el precio por evento se ancla en «menos que dos digitadores».
- **Externo → Gerente:** «Pides subdominio propio y SLA 99,9 %. Con Neon Launch sin SLA y un solo desarrollador, prometer 99,9 % es firmar una multa. 99,5 % mensual con crédito es lo máximo honesto.» **Aceptado.**
- **Externo → Interno:** «El riesgo de canibalización es real solo si el cliente SaaS era antes cliente operado. Las empresas de eventos NO son clientes de Golden hoy: son competidores que pasarían a ser clientes. Eso no canibaliza; cambia el negocio.» **Aceptado con matiz:** cláusula de no-competencia no se puede, pero sí precio distinto para «empresa de eventos» vs «empresa que hace SUS propios eventos» (corporativo), porque la segunda sí podría haber contratado a Golden para operar.
- **Gerente → Todos:** «Ninguno habló de que el código es público sin licencia. Si yo fuera malo, lo monto en mi servidor.» **Aceptado como riesgo #1 no financiero:** decisión de Juan David (licencia restrictiva tipo BSL/«source-available» o repo privado).
- **CFO → Externo:** «Los precios de la competencia están "estimados"; no los pongas en una propuesta comercial sin verificar.» **Aceptado:** se marcan como estimados en todo el documento.

### 2.3 Propuesta final del presidente

**Supuesto de cambio:** COP 4.000 = US$1. Todos los precios **+ IVA 19 %**, facturados en COP. Sin comisión de Golden sobre pagos de inscripción (van a la cuenta Wompi del cliente).

#### (b) Planes SaaS

| | **Evento suelto** | **Pro** | **Empresa** |
|---|---|---|---|
| **Precio** | **COP 390.000 por evento** (≈ US$95) | **COP 990.000 / mes** (≈ US$240) | **COP 2.490.000 / mes** (≈ US$600) |
| Para quién | Probar sin compromiso; corporativos con 2-4 eventos al año | Empresa de eventos con 2-4 eventos/mes | Empresa de eventos o universidad con operación continua y eventos sin internet |
| Eventos | 1 evento (hasta 3 días) | 4 eventos/mes (acumulables 2 meses) | Ilimitados (uso justo 15/mes) |
| Asistentes | hasta 500 | hasta 3.000/mes | hasta 15.000/mes |
| Excedente de asistentes | COP 600 c/u | COP 400 c/u | COP 250 c/u |
| Usuarios (cuentas de personal) | 5 | 15 | ilimitados |
| Registro por cédula, QR, lector PDF417, búsqueda, escarapela impresa desde el propio equipo (Brother QL-800) | ✔ | ✔ | ✔ |
| Formularios web de inscripción (gratuitos) + escarapela digital | ✔ | ✔ | ✔ |
| Formularios con pago (Wompi de SU cuenta, sin comisión de Golden) | — | ✔ | ✔ |
| Reconocimiento facial voluntario (consentimiento, cifrado, borrado a 7 días) | — | ✔ (requiere sus textos legales aprobados, ver riesgo) | ✔ |
| Estadísticas, exportación XLSX/CSV, informe del cliente | ✔ | ✔ | ✔ |
| Zonas, inventario de entregas, dependientes, ruleta, certificados | — | ✔ | ✔ |
| Servidor local sin internet (llave de producto) | — | 1 llave (COP 150.000/mes adicional) | 2 llaves incluidas; adicionales COP 100.000/mes |
| Marca propia (logo, colores, remitente de correo, pie de página) | logo en el evento | ✔ | ✔ + subdominio `empresa.app.golden-eventos.com` |
| Soporte | correo/WhatsApp en horario hábil, respuesta 1 día hábil | horario hábil + **guardia en noche de evento** (respuesta 30 min) con aviso 48 h antes | guardia en noche de evento 15 min + gerente de cuenta + 2 h de capacitación/mes |
| SLA | sin SLA | 99,5 % mensual, crédito 10 % | 99,5 % mensual, crédito 25 % |
| Exportar/borrar todo lo de la empresa | ✔ | ✔ | ✔ |
| **NO incluye** | facial, pagos, servidor local, guardia nocturna, zonas/inventario | subdominio, capacitación, más de 15 usuarios | personal en sitio, impresoras, etiquetas (eso es «Golden opera») |
| **Gancho** | «Menos que dos digitadores. Si no sirve, se lleva sus datos.» Primer evento gratis hasta 200 asistentes | «Pague lo mismo cada mes, haga 4 eventos, cobre inscripciones en SU Wompi sin comisión» | «Eventos sin internet con servidor en su portátil y alguien despierto la noche del evento» |

Reglas de precio: descuento **15 % por pago anual**; **corporativos que hacen sus propios eventos** (no empresas de eventos) +20 % porque sustituyen un evento operado por Golden (crítica Externo→Interno); precios se revisan cada enero con IPC + TRM.

#### (c) «Golden opera tu evento» (software + personal + equipos)

| Tramo de asistentes | Tarifa por asistente | Mínimo |
|---|---|---|
| hasta 300 | COP 15.000 | COP 1.800.000 |
| 301-1.000 | COP 12.000 | — |
| 1.001-3.000 | COP 9.000 | — |
| más de 3.000 | COP 7.000 (cotización) | — |

Incluye: software en plan Empresa durante el evento, 1 digitador por cada 125 asistentes esperados en hora pico, 1 coordinador, Brother QL-800 y etiquetas (una escarapela por asistente), tabletas, lector de cédula, router y servidor local si no hay internet, informe final. **No incluye:** viajes fuera de Bogotá (se cotizan aparte con la legalización), reconocimiento facial (+ COP 2.000/asistente por el tiempo extra en fila y el consentimiento), diseño gráfico de la escarapela más allá de la plantilla, reimpresiones masivas por cambio de datos del cliente.

Margen esperado con el costo interno de §2.1 pasada 3: evento de 500 → ingreso COP 6.000.000 vs costo ≈ COP 1.650.000 → **margen ~70 %** (antes de comercial y administración). Evento de 200 → COP 3.000.000 vs ≈ COP 900.000 → 70 %. Es coherente con lo que una empresa de eventos cobra por acreditación en Colombia (estimado: COP 8.000-20.000 por asistente según tamaño y ciudad).

#### (d) Margen por plan contra el tope de infraestructura

| Plan | Ingreso/mes | Nube marginal | Soporte estimado | Margen bruto | Margen % |
|---|---|---|---|---|---|
| Evento suelto (1 evento) | 390.000 | 12.000 | 60.000 (sin guardia) | ~318.000 | ~80 % |
| Pro (4 eventos) | 990.000 | 40.000 | 4 × 60.000 guardia parcial = 240.000 | ~710.000 | ~72 % |
| Empresa (10 eventos, 2 servidores locales) | 2.490.000 | 100.000 | 10 × 60.000 + 200.000 cuenta = 800.000 | ~1.590.000 | ~64 % |
| Golden opera (500 asistentes) | 6.000.000 | 12.000 | incluido en personal | ~4.350.000 | ~70 % |

- **El tope de nube (COP 160.000/mes) lo paga un solo cliente de cualquier plan.** La nube es irrelevante para el precio.
- **Punto de equilibrio del mantenimiento (COP 3.200.000/mes):** 5 clientes Pro, o 2 Empresa, o 10 eventos sueltos al mes.
- Lo que SÍ crece con los clientes y rompe el modelo si se ignora: la **guardia nocturna**. Con 10 clientes Pro habría ~40 noches de evento al mes: imposible para una persona. Antes de 6 clientes Pro hace falta un segundo técnico de guardia (COP 2-3 M/mes) o limitar la guardia a eventos avisados con 48 h y máximo 2 simultáneos.

#### (e) Lo que la plataforma NECESITA para venderse como SaaS (priorizado, con horas y qué ya existe)

| Prioridad | Pieza | ¿Existe hoy? | Qué falta | Horas |
|---|---|---|---|---|
| **S1** | **Cuenta/empresa suscriptora** (`accounts`): nivel por encima de `Tenant`; `tenants.account_id`, `staff_users.account_id`, `local_server_keys.account_id`, `payment_accounts.account_id`; Golden = cuenta 1 (`kind='interna'`) | **Parcial**: `Tenant` + `StaffUser.tenant_id` + `assert_event_tenant`/`scope_events_query` (apagados) | Migración, modelo, filtro por cuenta en listas de clientes, eventos, personal, llaves, cuentas de cobro, plantillas guardadas; pruebas con dos cuentas | 40-60 |
| **S2** | **Interruptor «cuenta interna» vs «SaaS»** que oculta CRM, legalizaciones, almacén, gastos de infraestructura, asignación de coordinadores (decisión 22-nov: CRM no va) | **Parcial**: `require_platform_role` ya bloquea a personal con `tenant_id` en gastos/satisfacción | Un `account.kind` y un filtro en `app/event_only.py`-style para rutas internas + barra lateral | 16-24 |
| **S3** | **Planes y límites en la base**: `plans`, `account_plans` (plan, vigencia, estado: prueba/activo/moroso/suspendido), límites (eventos/mes, asistentes/mes, usuarios, llaves) y funciones (facial, pagos, servidor local, zonas/inventario, marca propia); aplicación en «crear evento», «activar facial», «crear usuario», «crear llave», «carga masiva» | **No** (solo interruptores por evento y `AppSetting`) | Modelo + puntos de control + mensajes «su plan no incluye…» + pantalla «Mi plan» | 30-40 |
| **S4** | **Alta de empresa y primer administrador desde la app** (super_admin de Golden la crea; luego autoservicio con correo verificado y periodo de prueba 14 días) | **Parcial**: crear personal desde Configuración › Personal (admin+), restablecer contraseña por correo, `create_tenant` | Pantalla «Empresas» (super_admin), correo de bienvenida con enlace de primer ingreso, asistente «primer evento» | 16-24 |
| **S5** | **Estado de cuenta y cobro**: consumo del mes (eventos, asistentes = `access_logs` sin `PRUEBA`, usuarios), cargos, pagos recibidos, enlace de pago Wompi, suspensión por mora con aviso | **Parcial**: `infra_costs` reparto por actividad; *Payment Links* de Wompi (`docs/23`); `Event.billed_at` | Tabla `account_charges`, cálculo mensual en el Job de ops, pantalla «Estado de cuenta», aviso por correo | 24-32 |
| **S5b** | **Factura electrónica DIAN** | **No** | Primero manual (el contador factura en Siigo/Alegra y se adjunta el PDF en el estado de cuenta); integración API después | 8 (manual) / 40+ (API) |
| **S6** | **Marca propia por cuenta**: logo, colores (tokens `--gw-*` sobreescribibles), nombre y remitente del correo, pie de página legal; después subdominio por cuenta | **Parcial**: `Event.logo_mode/logo_path`, `DEFAULT_LOGO_URL` global, `digital_email_subject` por evento | `account_branding`, inyección en plantillas y correos, caché pública `/branding/<cuenta>/logo?v=` (diseño ya escrito en `docs/16` 7b) | 24-40 (+16 subdominio) |
| **S7** | **Exportar / borrar TODO lo de la cuenta** desde la app (admin de la cuenta): zip con todos sus eventos (motor `app/event_transfer.py`, hoy solo super_admin), personas, respuestas, pagos; «cerrar cuenta» = suspender 30 días → borrado definitivo con constancia | **Parcial**: exportar por evento (super_admin), `purge-data` por persona, `delete_tenant` solo archivado sin eventos, archivado L7 | Trabajo en Cloud Run Job por cuenta, descarga firmada, borrado en cascada con auditoría | 24-32 |
| **S8** | **Términos y política por cuenta**: aceptación de términos del servicio por el administrador (fecha, versión, IP enmascarada); aviso de privacidad y consentimiento facial de LA EMPRESA (responsable) con Golden como encargado | **Parcial**: `app/legal.py` versiona textos; `/privacidad`, `/terminos`; `audit_consent_logs` | `account_legal_texts` versionados, pantalla de aceptación, bloqueo de facial hasta tener texto aprobado; **contrato de encargo redactado por la auditora** (no son horas de código) | 16-24 + legal |
| **S9** | **Soporte dentro de la app**: «Pedir ayuda» (ticket con evento, pantalla y captura), estado del ticket, enlace WhatsApp de guardia solo en plan Pro/Empresa, página pública de estado (`/health` de los tres servicios) | **Parcial**: notificaciones, alertas de sistema, solicitudes de privacidad | Tabla `support_tickets`, correo a Golden, pantalla, página de estado estática | 16-24 |
| **S10** | **Encender y probar el aislamiento**: `ENFORCE_STAFF_TENANT=1` y `ENFORCE_STAFF_EVENT_SCOPE=1` en staging con dos cuentas; prueba automática; **prueba de penetración externa** antes del primer cliente (`docs/29` lo exige) | **Sí (código)**, no probado | Prueba `tests/test_aislamiento_cuentas.py`, corrida en staging, contratar pentest | 16 + externo |
| **S11** | **Llaves de producto por cuenta y por plan** (cantidad incluida, se cuenta contra el plan) | **Sí** la llave (`app/server_keys.py`) | `account_id` en `local_server_keys` y tope por plan (sale de S1+S3) | 8 |
| **S12** | **Onboarding sin código**: asistente «¿Qué necesito?» para el primer evento, plantillas de evento/escarapela/formulario por cuenta, archivo de ejemplo de carga (principio «dummy») | **Parcial**: `EventTemplate`, `SavedBadgeTemplate`, `SavedFormTemplate`, vista previa de cargas, tours | Asistente de bienvenida y plantillas semilla por cuenta | 16-24 |
| **S13** | **Correo saliente por cuenta** (remitente y respuesta a) sin exponer la cuenta Microsoft de Golden; SES o Graph con alias | **No** | Alias por cuenta en el envío (`app/mailer`), verificación de dominio opcional | 8-16 |
| **S14** | **Sitio web: sección «GoldenWeb para empresas» con planes y formulario de contacto** | **No** (`inicio.json` solo promete operación) | Otra sesión (sitio Astro) | 8-12 |
| | **Total para un primer cliente SaaS pagando** (S1-S5, S7, S8, S10) | | | **~190-270 h (5-7 semanas de una persona)** |
| | **Total completo (S1-S14)** | | | **~280-400 h** |

#### (f) Riesgos

| Riesgo | Por qué es real | Cómo se mitiga |
|---|---|---|
| **Precio demasiado bajo** | COP 390.000 por evento no paga una noche de guardia (COP 120.000) + 2 h de atención + el riesgo de que algo falle. Y subir precios después es más difícil que bajarlos. | El evento suelto NO trae guardia nocturna; guardia solo en Pro/Empresa. Revisar precios cada enero. Primer evento gratis en vez de descuento permanente. |
| **Canibalizar la operación de Golden** | Un corporativo que hoy paga COP 6 M por evento operado podría pagar COP 390.000 y poner a su gente. | Precio +20 % a corporativos; «Golden opera» siempre más barato por asistente que armar su propio equipo con digitadores externos; vender el SaaS a empresas de eventos (nuevo mercado), no a los clientes actuales de Golden. |
| **Soporte 24 h en noches de evento** | Una sola persona técnica (Juan David + Claude). Con 6+ clientes Pro hay noches simultáneas. | Guardia solo con aviso 48 h antes y máximo 2 eventos simultáneos en guardia; segundo técnico antes del cliente 6; runbook de noche (`docs/13` §7) y modo contingencia para que el cliente siga solo. |
| **Código público sin licencia** | Cualquiera puede leer y correr el código; el SaaS vende operación, no secreto. Sin `LICENSE`, legalmente «todos los derechos reservados», pero no disuade. | Decisión de Juan David: licencia *source-available* restrictiva (uso interno permitido, comercialización prohibida) o repositorio privado. No es trabajo técnico. |
| **Responsabilidad legal biométrica de terceros** | Los textos de la auditora son de Golden como responsable. Un cliente SaaS que use facial con esos textos está mal cubierto, y Golden como encargado también. | Facial apagado por cuenta hasta que suba sus textos aprobados (S8); contrato de encargo; opción «facial solo con Golden operando». |
| **Neon sin SLA y Cloud Run con 60 s por petición** | Prometer 99,9 % sería mentir. | SLA 99,5 % con crédito; modo contingencia; servidor local para eventos críticos. |
| **Cobro por asistente discutido** | El cliente puede discutir el conteo («esa persona entró dos veces»). | Contar asistentes ÚNICOS registrados por evento (`access_logs` distinto `user_id`, sin `PRUEBA`), visible en «Estado de cuenta» en vivo, nunca sorpresa a fin de mes. |
| **Moneda y TRM** | Costos en USD (Google, Neon), ingresos en COP. | Precios en COP revisados en enero con TRM; el panel de gastos ya guarda la TRM del día. |
| **IVA y retenciones** | El SaaS es gravado 19 %; los clientes retienen en la fuente. | Factura electrónica desde el primer cliente (contador); concepto claro en el contrato. |
| **Un solo desarrollador** | Cada cliente nuevo suma tickets; el desarrollo se frena. | Precio que financie un segundo técnico a partir del cliente 6; documentación ya fuerte (`docs/`). |

---

## 3. Qué se cambió en el código
**Nada.** Este informe es solo de análisis y propuesta; no se tocó ningún archivo fuera de este documento.

## 4. Qué queda pendiente y por qué (orden recomendado y horas)

1. **Decisiones de Juan David antes de cualquier hora de código** (0 h técnicas): licencia o privacidad del repo; confirmar los precios de §2.3 (o cambiarlos); confirmar que el mercado objetivo son empresas de eventos y no corporativos; pedir a la auditora el contrato de encargo y la viabilidad de facial para terceros.
2. **S10** encender y probar aislamiento en staging con dos cuentas (16 h): es barato y hoy es la pregunta #1 de cualquier prospecto.
3. **S1 + S2** cuenta suscriptora e interruptor interno/SaaS (56-84 h): ordena todo lo demás; sin esto los planes no tienen dónde vivir.
4. **S3 + S4** planes, límites y alta desde la app (46-64 h): con esto ya se puede dar una prueba de 14 días a un prospecto real sin tocar código.
5. **S7 + S8** exportar/borrar todo y textos legales por cuenta (40-56 h + auditora): sin esto no se firma con un gerente de ingeniería serio ni se activa facial a terceros.
6. **S5** estado de cuenta y cobro con enlace Wompi; factura manual por el contador (32-40 h).
7. **S6, S9, S11, S12, S13** marca propia, soporte, llaves por cuenta, onboarding, correo (72-128 h).
8. **S14** sitio web con planes (8-12 h, otra sesión) y reporte «margen por evento» en Gastos (8-12 h).
9. Pentest externo antes del primer cliente pagando (contratado, ~US$1.500-4.000 estimado).

## 5. Qué NO se pudo comprobar
- **Ningún precio de la competencia**: son recuerdos de 2024-2025, sin red desde Bash; verificar en sus sitios antes de citarlos.
- **La TRM** (se usó COP 4.000 como redondeo de trabajo) y los **jornales reales** de digitadores/coordinadores de Golden (la app los puede dar desde `EventExpense.kind='digitador'`, pero no se consultó ninguna base real).
- **Cuántos eventos hace Golden al mes de verdad** (se tomó el supuesto de `docs/13`: ~12) ni lo que Golden cobra hoy por evento operado.
- **Si `ENFORCE_STAFF_TENANT=1` funciona sin romper pantallas**: el código está, la prueba con dos clientes no se ha corrido (lo dice `docs/0C_cierre.md`).
- **Si el pedido 7b (logo por defecto desde Configuración) quedó implementado**: en `app/main.py` el logo por defecto sigue saliendo de `DEFAULT_LOGO_URL` (variable de entorno) o del archivo estático; no se vio una ruta `/branding/logo`.
- **Costos exactos de Brother QL-800 y rollos DK-22205 en Colombia** (estimados por memoria de precios 2024-2025).
- **Precios de Eventtia** (competidor local): no se pudo verificar; es el que más importa comparar.

## 6. Consejo en corto y veredicto

- **Contrario:** «No vendas SaaS todavía: vende "Golden opera" a más clientes; ahí está el 70 % de margen sin soporte nocturno ajeno.»
- **Primeros principios:** «El costo que importa no es la nube (COP 12.000/evento), es una persona despierta a las 9 pm. Pon el precio donde pague esa persona.»
- **Expansionista:** «Empresas de eventos de Medellín, Cali y Barranquilla con Brother y sin internet en pueblos: nadie les vende eso en pesos. Plan Empresa con servidor local es el producto.»
- **Forastero:** «El repo es público sin licencia y los textos legales son de Golden: dos cosas que un prospecto serio ve en la primera hora. Arréglalas antes de la primera demo.»
- **Ejecutor:** «S10 (16 h) y S1 (una semana) y ya puedes dar una prueba real a UNA empresa amiga. Lo demás se construye con ese cliente mirando.»

**Veredicto del presidente:** la plataforma puede venderse como SaaS con ~5-7 semanas de trabajo (S1-S5, S7, S8, S10), con precios de **COP 390.000 por evento / 990.000 Pro / 2.490.000 Empresa (+ IVA)** y **«Golden opera» desde COP 12.000 por asistente**; la nube no manda en el precio, la guardia nocturna sí. **UN siguiente paso:** Juan David decide hoy dos cosas no técnicas (licencia del repositorio y confirmar los precios/mercado objetivo) y, con eso, se arranca por **S10: encender `ENFORCE_STAFF_TENANT=1` en staging con dos clientes y una prueba automática** (16 h), porque es lo más barato y responde la primera pregunta de cualquier prospecto.
