# Fase 1A · Prueba con 2 digitadores nuevos (antes / después) y línea base

Qué se quiere saber: **cuántos segundos tarda un digitador en registrar a una persona** con la pantalla de hoy (`v0`) y con la pantalla nueva de la 1A (`1a`), y si el cambio es real y no efecto de aprender o de la suerte.
Esta página tiene tres partes: (1) la línea base sin código nuevo, (2) la medición exacta que agrega el PR1, (3) el guion de la prueba manual.
La medición no guarda cédulas ni nombres: solo duraciones (`access_logs.took_ms`) y la etiqueta de la pantalla (`access_logs.ui_flow`). Los informes son siempre agregados.

## 1. Qué mide la app (PR1)

- `took_ms` = milisegundos desde la **primera tecla** en cualquiera de los buscadores (o desde que se abre «Registrar nuevo», lo que ocurra primero) hasta el instante en que el quiosco **manda** el registro. Si el digitador borra todo lo escrito sin registrar, se descarta. Si hay aviso de DUPLICADO o reintento, sigue contando desde la misma primera tecla.
- **No incluye la respuesta del servidor** (el valor viaja dentro de la misma petición, no puede contar su propia respuesta). Por eso el cronómetro de un observador, que termina al ver «Acreditado», dará unos cientos de milisegundos más: es una diferencia casi constante, no afecta la comparación antes/después.
- Sin red: el tiempo se guarda junto al registro en la cola del dispositivo y se envía al sincronizar (los registros sin red miden el trabajo del digitador, no la espera de la red).
- Un registro hecho sin teclear (p. ej. desde la lista de recientes) o por un navegador con el JS viejo en caché **no se mide**: el informe dice cuántos registros del evento quedaron medidos (cobertura).
- El servidor acota el valor a 0..600000 ms (10 min) y lo ignora si no es válido; el registro se hace igual.
- `ui_flow`: `v0` es la pantalla de hoy. Las piezas siguientes de la 1A fijan `window.UI_FLOW = '1a'` en la pantalla nueva; hasta entonces todo sale como `v0`.
- **Informe** (solo admin y super_admin): sección «Tiempo por registro» al final de la pantalla Estadísticas del evento, o el JSON `GET /api/events/{id}/timing-report`: total, por pantalla y por digitador (mediana p50, percentil 90 p90, n). Con menos de 5 registros por grupo se marca «muestra pequeña». El digitador sale por su nombre de cuenta, nunca por su usuario (que es su cédula).

## 2. Línea base con eventos pasados (sin código nuevo)

Sirve para tener un «antes» de eventos que ya ocurrieron. **Es un proxy**: mide el tiempo entre dos registros consecutivos del mismo digitador, así que incluye esperas entre personas (filas de gente, pausas). Por eso se descartan los huecos de más de 5 minutos, y por eso la medida exacta (sección 1) es la que manda.
Se ejecuta en lectura contra una copia o con un usuario de solo lectura; la salida es agregada (no incluye cédulas). Reemplaza `:event_id` (o usa la variante de varios eventos).

```sql
-- Línea base: segundos entre registros consecutivos por digitador (huecos > 5 min descartados). Solo lectura.
WITH reg AS (
  SELECT registered_by_staff_id AS staff_id,
         "timestamp" AS at,
         EXTRACT(EPOCH FROM ("timestamp" - LAG("timestamp") OVER (PARTITION BY registered_by_staff_id ORDER BY "timestamp", id))) AS gap_s
  FROM access_logs
  WHERE event_id = :event_id
    AND record_type IN ('Existente', 'Nuevo')       -- registros reales; «Actualizado» es una edición
    AND registered_by_staff_id IS NOT NULL
    AND doubtful_reason IS NULL                      -- sin los ingresos de hora dudosa
)
SELECT staff_id,
       count(*)                                                         AS registros_con_hueco_valido,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_s))::numeric, 1) AS p50_s,
       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY gap_s))::numeric, 1) AS p90_s
FROM reg
WHERE gap_s IS NOT NULL AND gap_s > 0 AND gap_s <= 300
GROUP BY staff_id
ORDER BY registros_con_hueco_valido DESC;
```

Variante por evento (para comparar eventos pasados entre sí, sin separar por digitador):

```sql
WITH reg AS (
  SELECT event_id,
         EXTRACT(EPOCH FROM ("timestamp" - LAG("timestamp") OVER (PARTITION BY event_id, registered_by_staff_id ORDER BY "timestamp", id))) AS gap_s
  FROM access_logs
  WHERE record_type IN ('Existente', 'Nuevo') AND registered_by_staff_id IS NOT NULL AND doubtful_reason IS NULL
    AND event_id IN (/* ids de los eventos pasados */)
)
SELECT event_id, count(*) AS n,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_s))::numeric, 1) AS p50_s,
       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY gap_s))::numeric, 1) AS p90_s
FROM reg WHERE gap_s IS NOT NULL AND gap_s > 0 AND gap_s <= 300
GROUP BY event_id ORDER BY event_id;
```

Cómo leerla: un digitador que registra de corrido tiene huecos de 5 a 20 s; los huecos largos son pausas (se pierden en el corte de 5 min). Los registros hechos por el reconocimiento facial y por el autorregistro también cuentan como registros del digitador que operaba el equipo: si se quiere solo la ruta manual, agrega `AND registration_method IN ('tradicional', 'qr')`.
No guardes la salida con cédulas ni la pegues en el chat: solo las filas agregadas de arriba.

## 3. Guion de la prueba manual

**Quiénes:** 2 digitadores que **nunca** hayan usado el sistema (D1 y D2), 1 observador con cronómetro, 1 responsable que prepara el evento. Aviso y consentimiento previo de los dos digitadores (se miden sus tiempos; el informe es de grupo, sin evaluar a nadie).
**Dónde:** el servidor de pruebas (staging) o un evento de prueba local. **Nunca producción, nunca personas reales**: la base de la prueba es sintética (Excel con cédulas inventadas, p. ej. `personas_prueba_3000.xlsx` del generador de pruebas).
**Qué equipo:** el mismo equipo y el mismo lector de cédulas/QR para todas las tandas, Chrome normal. Sin impresión (autoimpresión apagada) para medir solo el registro.

### Preparación (responsable)
1. Evento de prueba «en curso» con 300 personas sintéticas cargadas y el modo «autoregistro» **prendido** (el caso de la puerta). Sin campos obligatorios extra.
2. Dos cuentas digitador nuevas (`prueba_d1`, `prueba_d2`) autorizadas en el evento. Una cuenta admin para leer el informe.
3. Tres listas impresas de tareas, con cédulas **distintas** por tanda (para que ninguna persona se registre dos veces, salvo los duplicados a propósito). Cada lista tiene 40 tareas en orden fijo:
   - 24 personas de la base, cédula escrita en el buscador (con el teclado).
   - 6 personas de la base, cédula leída con el lector / QR.
   - 4 personas de la base buscadas **por nombre** (la lista trae solo el nombre).
   - 3 altas nuevas (persona que no está en la base): se dan nombres y datos en una hoja.
   - 3 duplicados (ya registrados): el digitador debe confirmar o cancelar según la hoja.
4. Orden de las tandas (cancela el efecto de aprender y el de cansarse):

   | Tanda | D1 | D2 |
   |---|---|---|
   | 0 · práctica (10 min, lista de práctica, **no se mide**) | pantalla `v0` | pantalla `v0` |
   | 1 | `v0` · lista A | `1a` · lista A |
   | 2 | `1a` · lista B | `v0` · lista B |

   Descanso de 5 min entre tandas. (Mientras la pantalla `1a` no exista, se corre solo la mitad «antes»: tandas con `v0`, que da la línea base exacta; las tandas `1a` se repiten cuando la 1A esté lista, con digitadores que no hayan estrenado esa pantalla.)

### Durante la tanda
- El digitador recibe la lista y empieza. **No se le explican atajos**: se le da una sola inducción de 3 minutos de la pantalla (para qué es cada cosa), igual para los dos.
- El observador usa el cronómetro y anota por cada tarea: segundos desde que el digitador toca la primera tecla hasta ver «Acreditado», errores (cédula mal escrita, persona equivocada, clic de más) y si pidió ayuda. Una hoja por tanda. **No anota cédulas**: solo el número de tarea.
- Si el digitador se equivoca, se corrige como lo haría en la puerta; la tarea se marca «con error» y se deja en el conteo.

### Después de cada tanda
1. El responsable abre Estadísticas del evento (admin) → «Tiempo por registro», o `GET /api/events/{id}/timing-report`, y anota por digitador y por pantalla: n, p50 y p90. Guarda una captura **sin** nombres de cuentas reales (los de prueba están bien).
2. Se compara el p50 de la app con la mediana de la hoja del observador: deben ser parecidos, con la hoja unos 0,3 a 1 s por encima (la respuesta del servidor). Si difieren mucho, no se confía en la medición: revisar que el JS nuevo cargó (Ctrl+F5) y que la cobertura sea alta.
3. Se limpian los registros de la tanda (o se usa un evento nuevo por tanda) para que la siguiente empiece con la misma base.

### Qué se reporta
- Por pantalla (`v0` vs `1a`): n, p50, p90, tareas con error y ayudas pedidas; por tipo de tarea (teclado, lector, por nombre, alta, duplicado).
- Criterio de éxito propuesto: p50 de `1a` **al menos 25 % menor** que el de `v0` en las tareas de teclado y lector, y p90 que no empeore; ninguna tarea con más errores. Con solo 2 digitadores y ~40 tareas por tanda es una **señal, no una estadística**: se decide con esto, pero se confirma con los datos del primer evento real (el informe del evento ya los trae por pantalla y por digitador).
- Observaciones libres de los 2 digitadores (¿qué le costó?, ¿qué haría distinto?).

### Reglas de privacidad
Solo staging o local; personas sintéticas; no se guardan fotos; las hojas del observador no llevan cédulas ni nombres reales; los informes son agregados. Los resultados se archivan en `docs/etapa/` como cifras (sin datos de los digitadores más allá de «D1/D2»).
