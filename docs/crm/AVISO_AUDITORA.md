# Aviso a la auditora — borrador (para que Juan David lo envíe ANTES de cargar contactos reales del CRM)

Asunto: Aviso previo — tratamiento de datos de contactos de clientes en el nuevo CRM de Golden

Cordial saludo.

Golden Eventos y Logística S.A.S. va a trasladar su CRM actual (SuiteCRM, alojado en Colombia Hosting) a un módulo propio dentro de GoldenWeb. Con ese traslado se cargarán datos de contacto de las personas de nuestras empresas clientes (nombre, cargo, correo electrónico y teléfono) y el historial de comunicaciones comerciales asociado.

Para que lo evalúe a la luz de la Ley 1581 de 2012 y su decreto reglamentario, le informamos:

1. **Finalidad:** gestión comercial y de relación con clientes (cotizaciones, seguimiento, facturación). Estos datos no se usarán para reconocimiento facial ni se mezclan con los datos biométricos de la plataforma.
2. **Origen:** son datos que Golden ya trata hoy en su CRM actual; no se recogen datos nuevos con este traslado.
3. **Dónde quedarán los datos (transmisión a encargados fuera de Colombia):**
   - **Base de datos:** Neon (PostgreSQL gestionado), que opera sobre infraestructura de Amazon Web Services en la región **us-east-1 (Virginia, Estados Unidos)**.
   - **Aplicación y archivos:** Google Cloud, región **us-east4 (Virginia, Estados Unidos)**.
   - Cambia el encargado de la infraestructura (de Colombia Hosting a Neon/AWS y Google Cloud). Le pedimos indicar si se requiere actualizar el aviso de privacidad, la autorización de los titulares o las cláusulas de transmisión con estos proveedores.
4. **Seguridad:** acceso solo para el personal comercial y administrativo autorizado, registro de cambios (quién, qué y cuándo), respaldos de la base, cifrado en tránsito y control de roles.
5. **Derechos de los titulares:** consulta, actualización y supresión se atenderán sobre este mismo módulo; la supresión de un contacto elimina también su historial de cambios y las notas que lo mencionan. Las copias de respaldo se renuevan según su política de retención.
6. **Carga:** la importación se hará una sola vez, primero con una muestra con datos ficticios en pruebas y solo después con los datos reales, con respaldo previo.

Le agradecemos su concepto y cualquier ajuste que considere necesario antes de la carga de datos reales. No cargaremos contactos reales hasta contar con su respuesta.

Atentamente,
Juan David [apellido y cargo], Golden Eventos y Logística S.A.S.
