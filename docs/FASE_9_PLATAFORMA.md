# Fase 9 — Plataforma (alertas, copias, panel de gastos)

## D. Panel de gastos — pestaña «Eventos» (análisis de satisfacción y tiempos)

**Quién la ve:** solo `admin` y `super_admin` (`require_role("admin")`). **Dónde:** `/gastos` → pestaña «Eventos». **Código:** `app/event_analytics.py` (cálculo puro, sin base), `app/routers/gastos_eventos.py` (API), `templates/_gastos_eventos.html`, `static/js/gastos-eventos.js`, `static/css/gastos-eventos.css`. **Pruebas:** `tests/test_analitica_eventos.py`. **Sin migración:** todo sale de tablas que ya existen.

### API (todas GET, solo admin, caché en memoria de 60 s por combinación de filtros)
`/api/gastos/eventos/` + `panel` (todo junto; es lo que usa la pantalla) · `resumen` · `satisfaccion` · `tiempos` · `alertas` · `filtros` (clientes y comerciales para los selectores) · `exportar` (Excel).
Filtros: `desde`, `hasta` (AAAA-MM-DD; por defecto los últimos 12 meses; se filtra por la fecha de FIN del evento), `cliente` (id), `comercial` (id de cuenta), y umbrales de alertas `low` (1-3), `overdue` y `wait` (días).

### Qué eventos cuentan
Eventos cuyo `end_date` cae en el rango. **Se excluyen** los de prueba: código que empieza por `LOAD-` (pruebas de carga). `Event` no tiene bandera «de prueba»; si algún día se agrega, se cambia `TEST_EVENT_PREFIXES`/`load_events` en un solo lugar. No se cuentan asistentes, así que la persona `PRUEBA` no interviene. Los archivados SÍ cuentan (siguen siendo historia).

### Fórmulas
- **Calidad (1-3):** Malo = 1, Bueno = 2, Excelente = 3 (`survey_def.RATING_SCORES`); «No aplica» no puntúa. Promedio por pregunta = media de los puntajes de esa pregunta. Promedio de un evento = `survey_responses.avg_score`.
- **NPS:** `%promotores (9-10) − %detractores (0-6)` sobre las respuestas a «¿recomendaría?» (0-10); los 7-8 son neutros. Resultado de −100 a 100, redondeado a entero. Sin respuestas → «—».
- **Tasa de respuesta:** encuestas respondidas ÷ eventos «entregados» (tienen enlace de entrega o están facturados) × 100.
- **Quieren otro evento:** respuestas «Sí» ÷ (Sí + No) de la pregunta `q8_next_event`. **Ya crearon uno:** de los «Sí», cuántos clientes crearon un evento con `created_at` posterior a su respuesta (inferido; es un cálculo, no un dato registrado).
- **Evolución mensual:** por mes en que se contestó la encuesta, promedio de calidad y NPS.
- **Mejor/peor evaluados:** top 5 por promedio de calidad (desempata por recomendación). **Por comercial / coordinador / cliente / ciudad:** promedio de calidad y NPS de los eventos de cada grupo, de mejor a peor.
- **Tiempos (días, con decimales):** `fin del evento` = el final del día `end_date`.
  - Cerrar = `finalized_at − fin`. Subir la base = `final_db_uploaded_at − fin`. Facturar = `billed_at − finalized_at` y `billed_at − fin`.
  - Por cada etapa: n, promedio, **mediana** (la mitad tarda menos) y **P90** (9 de cada 10 tardan menos), con interpolación lineal. Una duración negativa o con fecha faltante no entra (no rompe el promedio).
  - Mensual = por mes del fin del evento. Por comercial/cliente: mismas estadísticas, ordenado del que más tarda en facturar al que menos.
- **Resumen en lenguaje claro:** «Este mes: NPS +X, N encuestas respondidas, N eventos facturados, tiempo promedio de facturación D días». «Este mes» = mes local actual; NPS y encuestas del mes de respuesta; eventos facturados del mes de `billed_at` dentro del filtro; días = promedio fin → facturado de esos eventos.

### Alertas (umbrales configurables en la pantalla, «Umbrales de las alertas»)
- **Baja satisfacción:** promedio ≤ `low` (por defecto 1,8) o recomendación de detractor (0-6).
- **Atrasados sin facturar:** Finalizados hace más de `overdue` días (30) sin `billed_at`; enlaza al evento.
- **Encuestas sin responder:** Facturados hace más de `wait` días (7) sin encuesta; indica si el cliente abrió el enlace.
- **Clientes a la baja:** la última encuesta del cliente quedó ≥ 0,3 por debajo de la anterior (necesita 2 o más).

### Privacidad
Solo eventos, clientes y cuentas del personal; ningún dato de asistentes. Los comentarios son texto libre del cliente (la encuesta no pide ni guarda quién responde) y solo los ve el administrador; se muestran con `textContent`. El Excel pasa por `xlsafe.safe_workbook`. Nada de esto se escribe en logs ni toca la base con frecuencia: se calcula cuando un administrador abre o filtra la pestaña.

### Gráficos
SVG propio (barras horizontales, columnas 0-10, líneas mensuales), sin librerías ni costo; colores con tokens `--gw-*` (claro/oscuro) y cada barra/punto con `<title>` y su valor escrito; junto a cada gráfico hay tabla o cifras.
