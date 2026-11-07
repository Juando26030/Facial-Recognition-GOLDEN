# Fase 2 — alcance ajustado (decisiones de Juan David, 7-nov-2026)

Reemplaza el §7 del plan maestro (`29_PLAN_MAESTRO…`) para lo que falta. Decisiones registradas:

1. **Lo visual ya hecho no se toca.** Los «3 botones por rol» del inicio ya quedaron bien en la Fase 1.7. Lo nuevo se construye con lo que ya existe y con los mismos estándares (`ux/ESTANDARES_VISUALES.md`, tokens `--gw-*`, `.gw-*`).
2. **Calendario:** lo ven todos los roles del personal EXCEPTO digitador temporal y cliente. Cada tarjeta de evento muestra la información de la plantilla, organizada y bonita; puede ser larga (los días con un solo evento dejan espacio). Al dar clic en «Editar» sale todo como hoy.
3. **Configuración (solo super_admin y admin) → «Diseñar plantilla para eventos»:** dos pantallas con el estilo del editor de formularios web (arrastrar, mover, cambiar parámetros; sin tipografías):
   - **Vista de creación de evento:** qué información pide «Nuevo evento», en qué orden, cuáles campos son obligatorios.
   - **Vista de calendario:** de todos los campos posibles, cuáles salen en la tarjeta y dónde (izquierda, derecha, abajo…). Solo visual.
4. **Tipos de campo:** texto corto · texto largo · lista desplegable abierta (el admin define las opciones) · dinero · número · comercial (lista de comerciales existentes) · coordinador (lista de coordinadores) · fecha y hora con título propio (inicio, fin, montaje, hora montaje, inicio/fin de registro…) · país (todos los países, con búsqueda escribiendo) · ciudad (las del país elegido; si no está, texto libre) · dirección con mapa (escribir o marcar con clic) · contacto del evento (texto + teléfono) · colores de pañoletas (los colores guardados, igual que en el formulario) · inventario (el admin define los «tipos de inventario» —X, Y, Z— y cada uno con cantidad y un tipo/referencia en lista) · interruptores del evento (reconocimiento facial, control de inventario, control de áreas, ruleta…). `Código` y `Nombre` ya existen.
5. **Los interruptores de «Nuevo evento» y los de «Parámetros del evento» son lo mismo:** una sola fuente de datos, dos pantallas. Si no se definen al crear, se definen después en Parámetros.
6. **Crear evento desde «Eventos»** además de desde «Clientes»: el mismo formulario, pero pide elegir el cliente en una lista con buscador de texto. Desde un cliente, el cliente ya viene asignado.
7. **Apellido en «Registrar nuevo»:** se detecta solo al cargar la base. Si la base usó «nombre» con nombre y apellido juntos (sin columna de apellido o vacía), el apellido NO es obligatorio y se puede desmarcar; si usó nombres y apellidos por separado, ambos son obligatorios.
8. **Páginas públicas:** siguen congeladas.
9. **VM antigua:** se cierra lo que no se use en Google Cloud; si no hace nada, se puede borrar (con instantánea final y revisión previa).

## Relación con otras fases
Los puntos 3–6 adelantan lo que el plan tenía en la Fase 5 (ficha configurable, asistente de creación, inventario por cantidad). Al cerrar la Fase 2 se actualiza la Fase 5 para no duplicar.

## Respuestas del 7-nov-2026 (10:17)
- **Mapa:** gratis (OpenStreetMap con búsqueda de direcciones); Google Maps queda para después si hace falta.
- **Eventos existentes:** NO se migran todavía. Primero se construye la plantilla; cuando Claude ya la lea y entienda qué va en cada campo, se hace la migración de los eventos actuales.
- **Campos base:** código, nombre y cliente siempre obligatorios y no quitables; la obligatoriedad del resto la decide el admin.
- **Calendario, quién:** super_admin, admin, comercial y coordinador. Digitador (no existe digitador fijo por ahora) y cliente no lo ven.
- **Calendario, flujo:** clic en un evento abre un cuadrito superpuesto con las mismas acciones de la fila de Eventos/Clientes (Editar, Exportar, Cambiar estado, Ingresar); clic fuera lo cierra. Mismos permisos de siempre: la acción que el rol no puede (p. ej. Eliminar) no aparece.
- **Países y ciudades:** lista fija dentro de la plataforma, sin servicios externos.
- **Orden de entregas:** (1) calendario con los datos actuales y el cuadrito de acciones; (2) plantilla de creación y de calendario; (3) crear evento desde Eventos con selector de cliente; (4) mapa e inventario; después, migración de eventos existentes.
