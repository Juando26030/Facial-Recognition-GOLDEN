# Fase 5 — Decisiones de Juan David (8-nov-2026)

- **Tipos de evento:** no se definen lista; salen de la plantilla de evento (motor de plantillas ya construido).
- **Campos clave** (los que avisan por correo al cambiar y quedan en el historial por campo): los marcados **obligatorio** en la plantilla del evento.
- **Estado «Facturado»:** estado configurable (base `finalizado`). «Finalizado» = terminó el registro. «Facturado» = el cliente pagó y el contrato está cerrado; habilita la entrega al cliente. Lo pueden poner **cualquier comercial o administrador**; queda registrado **quién y cuándo**.
- **Jornada (campo informativo, calculado de la hora de inicio y fin):** 0–6 h «Media jornada»; 6–9 h «Jornada intermedia» (entre media y completa); 9–12 h «Jornada completa»; más de 12 h «Jornada extendida». Límites exactos (6, 9, 12) por confirmar al construir.
- **Flujo de entrega al marcar «Facturado»:** se genera un enlace asociado al evento (visible al editar el evento, con copiar). La comercial puede copiarlo y mandarlo a mano, o marcar «enviar al correo del cliente» (por defecto **desmarcado**), con un correo redactado: el evento finalizó, se pide diligenciar una **encuesta de satisfacción** y, al enviarla, puede **descargar la base de datos**.
- **Qué base recibe el cliente:** la **base final procesada por humanos**, subida en el evento (campo nuevo «Subir base de datos final», que se perdió al hacer el motor de plantillas), no la de estadísticas.
- **Aviso a la comercial:** cuando el coordinador sube la base final, llega un correo automático a la comercial del evento: «ya se subió la base; revisa si ya se puede facturar». Ella decide y factura.
- **Inventario:** el Super Admin define en Configuración la estructura (categorías) y los productos del catálogo; esos productos aparecen como campos de inventario al crear el evento.
- **Roles nuevos:** almacén y contabilidad (por el sistema de roles múltiples); sus correos salen de las cuentas con ese rol.
- Pendiente de diseño: la encuesta de satisfacción se construye con el motor de formularios web (no existe aún en el código).

## Aclaraciones (8-nov-2026, 23:40)
- **Jornada** es un campo de la plantilla del evento como cualquier otro: el admin decide si se agrega o no, y si se muestra o no en la vista de calendario.
- **Encuesta de satisfacción:** por ahora una encuesta normal genérica (Juan David define sus preguntas después). **Sus respuestas se guardan aparte**, en estructura propia (no mezcladas con los formularios de inscripción), porque en una fase posterior alimentan la analítica para gerencia: promedios de satisfacción por mes, por evento y por cliente. Diseño: tabla propia con evento, cliente, fecha, respuestas por pregunta (con puntaje numérico donde aplique); sin datos personales innecesarios; no se purga con la biometría.
