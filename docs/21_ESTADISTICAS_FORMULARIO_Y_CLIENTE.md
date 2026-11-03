# Estadísticas de un formulario y acceso de cliente por formulario (3-nov-2026)

## Qué hace
1. **Página «Estadísticas» de cada formulario** (`/kiosk/{evento}/formularios/{formulario}/estadisticas`, coordinador+): cifras grandes (inscritos, cupos usados / faltantes, visitas, última inscripción), **cupos** con barras de progreso (total y uno por cada regla de «Cupos por variables»: usados, porcentaje y cuántos faltan), una tarjeta por **variable de elección** (listas, opciones, casillas) con la cantidad y el porcentaje de cada opción a la vista, y la curva de inscripciones. Es responsive (1 columna en celular, 2 o 3 en computador), usa los tokens de `design-system.css` y respeta el tema claro/oscuro. Datos: `GET /api/events/{evento}/forms/{formulario}/stats` (`app/form_stats.py`).
2. **Acceso de cliente por formulario**: en el editor del formulario, botón **«Acceso para cliente (solo estadísticas)»**. Crea un usuario (`cliente-f<id>-xxxx`) y una contraseña temporal segura que se muestra **una sola vez**, con vigencia en días (30 por defecto, máximo 180). El cliente entra por `/login` y solo ve `/mi-formulario`: las estadísticas de ESE formulario. Ahí mismo se ven y se quitan los accesos.
3. La pestaña «Analítica» del editor ahora dibuja gráficas grandes (más altas, letra legible, cantidad en cada barra) y enlaza a la página nueva.

## Reglas de seguridad
- **Solo agregados**: de las respuestas únicamente se cuentan campos de elección; nunca nombres, cédulas, correos, textos libres ni listas de personas.
- **Aislamiento sin tocar los permisos del evento**: la cuenta es rol `cliente` pero NO se autoriza a ningún evento (sin `event_staff_authorizations`), así que `get_event_for_staff` le da 403 en todo lo del evento y en los demás formularios. Su formulario sale siempre de la fila `form_client_users`, nunca de un parámetro. Los clientes de evento no cambian.
- Crear/quitar accesos: comercial, admin o super_admin (igual que las cuentas cliente de evento); ver la lista y las estadísticas: coordinador+. Respeta `ENFORCE_STAFF_TENANT` / `ENFORCE_STAFF_EVENT_SCOPE` (vía `get_event_for_staff`) y que el formulario sea del evento de la URL.
- Vencimiento: por `expires_at` del acceso (no por el estado del evento, para que el cliente vea las inscripciones mientras el evento aún está «Creado»). Al vencer, o al quitar el acceso o borrar el formulario, la cuenta deja de funcionar.
- Migración `0080_form_client_users` (aditiva, una tabla). Código: `app/form_client.py`, `app/routers/form_client.py`, `app/form_stats.py`.

## Cómo se usa
Editor del formulario → «Acceso para cliente (solo estadísticas)» → (opcional) nombre y días → «Crear acceso» → «Copiar los datos» y enviarlos al cliente. Para cortar el acceso: «Quitar acceso» en la misma ventana.
