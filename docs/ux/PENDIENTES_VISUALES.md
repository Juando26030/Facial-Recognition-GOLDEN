# Pendientes visuales (entrada de la Fase 2)

Lo que se ve feo o inconsistente fuera del alcance de la pieza en curso. Una línea por hallazgo: pantalla · qué falla · captura si hay.

| Pantalla | Qué falla | Visto en |
|---|---|---|
| Parámetros del evento (resuelto 2026-11-05, rama `feat/visual-parametros`) | Reingeniería visual hecha: pestañas por sección con resumen, `gw-page` y tema oscuro, sin `style=` ni hex ni emojis, tablas `.gw-table`, ayuda en «?», guía de 3 pasos y recorrido de primera vez. Quedan los puntos de las dos filas siguientes. | PR de la rama |
| Parámetros del evento · editor de opciones | `static/js/option-tools.js` (lista de opciones de un campo y ventana «traer de otro evento») sigue con estilos en línea y colores sueltos; no se tocó porque lo comparten otras pantallas y tiene su propia prueba (`option_tools_dom_check.js`). | Revisión de la reingeniería |
| Parámetros del evento · formulario de persona y avisos | `person-form-designer.js` (diseñador del formulario de persona) y `toast.js` (`showConfirm`/`showPrompt`) conservan su aspecto propio; en la ventana de «Borrar campo» el texto largo sale en una sola pieza. `app/biometric_setup.py` devuelve un titular con emoji (✅): la pantalla lo recorta, pero conviene quitarlo en el servidor. | Revisión de la reingeniería |
| Parámetros del evento · pruebas con personas | Falta probar con lector de pantalla (NVDA/VoiceOver) las pestañas (flechas, Inicio, Fin), los «?» y el recorrido, y revisar capturas en claro/oscuro a 360 px y en iPad. Decisión abierta: en Parámetros todo (incluidas las casillas) se aplica con «Guardar cambios»; solo lo marcado «Al instante» actúa de inmediato (excepción documentada en ESTANDARES §4). | Revisión de la reingeniería |
| Registro (`kiosk_registro.html`) | Plan 7 la pasó a la base nueva y al tema oscuro; quedan con estilos en línea heredados los modales internos (alta/edición, escáner, MRZ) y las filas/botones que arma `directory.js` (clase `golden-btn`, restilizados por `registro.css`). Revisar contraste en oscuro en staging. | Plan 7 · Registro limpio |
