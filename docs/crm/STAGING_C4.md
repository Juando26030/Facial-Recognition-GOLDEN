# Prueba en staging — C4 (ganada → cliente y evento, «Mi día», tableros)

Solo con datos ficticios, en staging (`CRM_ENABLED=1`). Producción NO se toca.

## Antes
1. Correr las pruebas con base: `python -m pytest -q tests/test_crm_ganada.py tests/test_crm_oportunidades.py` (escritas, sin ejecutar).
2. No hay migración nueva: C4 usa los índices que ya existen (`ix_crm_act_owner_due`, `ix_crm_opps_owner`). La 0134 reservada queda SIN USAR.
3. El contador `event` debe estar listo y por encima de todo código de evento existente (staging: piso de prueba 800000; ver `docs/crm/CODIGOS.md`). Si un evento ya tiene ese código, ganar la oportunidad responde 409 y no crea nada.

## Criterios de éxito
1. En `/crm/oportunidades`, arrastrar una oportunidad ficticia a «Ganada» (o usar «Mover a…»): el aviso dice que se creará el evento y el cliente; al confirmar queda ganada.
2. En la ficha aparece la insignia «Evento N» (N = el número de la oportunidad). En Eventos existe un evento con ese código, en estado «creado», con el nombre, la fecha de inicio y la ciudad de la oportunidad, y con la persona de prueba (cédula PRUEBA).
3. Si la cuenta no era cliente, ahora lo es (con el mismo número de la cuenta); si ya lo era, no se crea un cliente nuevo.
4. El evento queda con la comercial dueña de la oportunidad (si sigue activa y es comercial); si no, sin comercial.
5. Ganar una oportunidad cuyo código ya existe como evento: error 409 claro, la oportunidad sigue abierta y no se crea ni cliente ni evento (todo o nada).
6. Una oportunidad ganada con evento no se puede sacar de «ganada» (409).
7. Una oportunidad ya ganada sin evento (antigua o importada) muestra «Crear el evento»; al pulsarlo se crea solo el evento.
8. Perder o reabrir una oportunidad nunca crea evento.
9. Con el cliente archivado o la cuenta archivada, ganar responde 409 con el motivo.
10. `/crm/mi-dia`: muestra vencidas, de hoy, recordatorios, oportunidades sin próxima actividad, por cerrar en 14 días y cotizaciones que vencen en 7 días; solo lo mío. «Marcar hecha» la saca de la lista.
11. «Mi día» y los tableros se cargan al abrir y al pulsar «Actualizar»/«Ver»; no hay nada que se refresque solo (la base de Neon puede dormir).
12. `/crm/tableros`: embudo abierto por etapa, ganadas/perdidas del periodo, tasa de cierre, actividades y cotizaciones. COP y USD aparecen separados, nunca sumados.
13. El comercial solo ve lo suyo (aunque pida otro responsable por la dirección); el admin ve todo el equipo, la tabla por responsable y puede filtrar por una persona.
14. Un usuario «coordinador» no ve ni la API ni las pantallas.
15. Revisar en 1000/1100/1280/1500 y 390 px, claro y oscuro: sin desbordes, objetivos ≥ 44 px.

## DECISIÓN (valores por defecto tomados)
- Ganar desde el tablero o la ficha crea el cliente y el evento en la MISMA transacción que el cambio de etapa (todo o nada).
- El evento nace con el MISMO número de la oportunidad (`event_code`), en estado «creado», con nombre, inicio y ciudad de la oportunidad. No exige los campos de la plantilla de evento: lugar, horarios y demás se completan en Eventos.
- El evento creado desde el CRM trae lo de siempre: persona de prueba, enlace corto, compromiso digital (si hay texto aprobado) y exigencia del enlace personal sin fecha de nacimiento.
- El coordinador del evento no se asigna solo (lo elige quien administra en Eventos).
- «Mi día»: umbrales de 14 días (cierre) y 7 días (cotizaciones); listas de máximo 50; el «hoy» se calcula en hora de Bogotá.
- Tableros: periodos de 30, 90 o 365 días (otro valor = 90); cerradas, actividades hechas y cotizaciones se miden en el periodo; el embudo abierto y lo pendiente son el estado de hoy.
- La tasa de cierre es ganadas ÷ (ganadas + perdidas) del periodo, sin contar las abiertas.
- Ley 1581: borrar una cuenta o un contacto en el CRM no toca el cliente ni el evento de la plataforma (tienen su propia retención y su propio borrado de biometría); la oportunidad desvincula el evento (`event_id` pasa a NULL si el evento se borra).
- Consultas por pantalla: «Mi día» = 5 consultas acotadas; tableros = 5 a 6 consultas agrupadas; ganar = una transacción corta.

## Revisión visual (12-nov-2026, arnés con datos ficticios)
«Mi día» (normal, 40 actividades, textos larguísimos, vacío) y tableros (equipo, comercial, vacío) a 1000/1280 y 390 px, claro y oscuro: sin desbordes. Corregido: en celular el valor de cada barra caía solo en otra línea y el filtro «Ver» quedaba suelto.
Pendiente a mano en staging: ganar con el cliente nuevo y abrir el evento en Eventos para confirmar que la plantilla de evento no pide nada más.
