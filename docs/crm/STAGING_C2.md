# Prueba en staging — C2 (embudos, oportunidades, leads, tablero)

Solo con datos ficticios, en staging (`CRM_ENABLED=1`). Producción NO se toca.

## Antes
1. Correr las pruebas con base (≈5 min): `python -m pytest -q tests/test_crm_pipeline.py tests/test_crm_actividades.py tests/test_crm_oportunidades.py tests/test_crm_leads.py tests/test_crm_c2_limites.py` (escritas, sin ejecutar).
2. Migraciones 0131 y 0132 aplicadas en staging.

## Criterios de éxito
1. `/crm/embudos` (admin): se ve el embudo «Eventos» con sus etapas; se puede crear una etapa, renombrarla, reordenarla con las flechas y archivarla. Una etapa con oportunidades abiertas no se archiva.
2. `/crm/oportunidades`: crear una oportunidad ficticia; recibe el siguiente número de evento y queda en la primera etapa abierta.
3. Arrastrar la tarjeta a otra columna (o «Mover a…») la mueve; al pasar a «Perdida» pide el motivo. «Ganada» la cierra y NO crea evento (eso es C4).
4. Los totales de cada columna separan COP y USD y muestran el valor ponderado; nunca se suman monedas distintas.
5. Una columna con más de 50 tarjetas muestra «Ver más» y continúa en la misma columna.
6. Abrir dos pestañas sobre la misma oportunidad, guardar en una y luego en la otra: la segunda avisa que fue modificada.
7. En la ficha, el historial no muestra el texto de descripción ni del siguiente paso, solo que cambiaron.
8. `/crm/leads`: crear lead, convertirlo (cuenta nueva y cuenta existente, con y sin oportunidad); un segundo intento de conversión se rechaza.
9. Suprimir un lead (admin): pide el nombre exacto y el motivo; el aviso de revisión queda visible.
10. Suprimir un contacto borra los leads con el MISMO correo y avisa de los que solo coinciden en nombre o teléfono.
11. Un usuario «coordinador» no ve ni la API ni las pantallas del CRM.
12. Revisar en 1000/1100/1280/1500 y 390 px, claro y oscuro: sin desbordes, texto ≥ 14 px, objetivos ≥ 44 px.

## DECISIÓN (valores por defecto tomados)
- El tablero muestra Ganadas/Perdidas de los últimos 90 días; la lista trae todo.
- Las etapas cerradas van siempre al final.
- Un lead no tiene página propia: se gestiona desde la lista.
- El filtro por nombre de oportunidad no ignora tildes (el de cuenta sí).
- Al suprimir un contacto solo se borran leads con correo idéntico; los homónimos se revisan a mano.
- Consultas por pantalla: tablero = 2 consultas + catálogo en memoria 30 s.
