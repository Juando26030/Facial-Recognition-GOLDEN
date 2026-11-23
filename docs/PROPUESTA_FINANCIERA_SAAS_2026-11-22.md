# Propuesta financiera del SaaS de GoldenWeb 2.0 (borrador para revisión de Juan David · 22-nov-2026)

**Estado: PROPUESTA, no decisión.** Es la propuesta del reporte 07 de la revisión integral (`docs/revision_2026-11-22/07_saas_prospectos_finanzas_planes.md`), reunida en un solo documento para que Juan David la revise, cambie lo que quiera y diga qué queda. Nada de esto está cargado en la aplicación: los planes y límites se configuran en «Empresas (SaaS)» (`/plataforma`) cuando se decidan.

## Qué hay que decidir (en este orden)
1. **Tipo de cambio y moneda:** la propuesta usa COP 4.000 = US$1, precios en pesos + IVA 19 %. ¿Se mantiene?
2. **Los tres planes** (evento suelto, Pro, Empresa) y sus precios de la tabla (b). ¿Se cambia algún precio, tope de eventos, asistentes o usuarios?
3. **«Golden opera tu evento»** (c): tarifas por asistente y mínimo.
4. **Primer evento gratis** hasta 200 asistentes (propuesto como gancho en vez de descuento permanente).
5. **Descuento anual** 15 % y **recargo 20 % a corporativos** que hacen sus propios eventos.
6. **A quién se vende primero:** empresas de eventos (mercado nuevo) y no los clientes actuales de Golden (para no canibalizar la operación).
7. **Guardia nocturna:** solo planes Pro y Empresa, con aviso de 48 h y máximo 2 eventos simultáneos; segundo técnico antes del cliente 6.
8. **Licencia del código:** el repositorio es público. Decidir entre licencia que prohíba comercializar, o repositorio privado.
9. **Presupuesto de infraestructura:** el tope de US$40/mes (≈ COP 160.000) lo paga un solo cliente de cualquier plan; la nube no define el precio.

Lo que no puede venderse todavía (falta construir): facturación y estado de cuenta, marca propia por empresa, aislamiento probado entre empresas y prueba de penetración externa. Detalle y horas en la sección «Lo que la plataforma necesita» del reporte 07 (~190-270 h para el primer cliente pagando).

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

## (f) Riesgos

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
