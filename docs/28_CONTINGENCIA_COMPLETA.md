# 28 · Registro completo sin conexión (contingencia completa)

Pedido de Juan David (25-nov-2026): cuando se cae el internet, la pantalla de Registro debe permitir **exactamente lo mismo que con conexión**: ver todos los campos de la
persona y escribir datos que queden guardados. Encendido por defecto (la auditora ya aprobó guardar estos datos en el dispositivo, según Juan David). Sin recargar Cloud Run.

## Decisiones

- **Sin descargas nuevas.** La copia completa son las MISMAS filas que el directorio ya baja con red (`/api/users` y `/api/users/changes`). Cero peticiones extra al servidor.
- **Cifrada en reposo siempre.** AES-GCM 256 con la clave no extraíble del equipo, en bloques de 400 personas (almacén `people` de `golden-contingency-<evento>`).
- **Vive y muere con la lista local.** Se borra al cerrar sesión, al finalizar el evento, al perder el permiso y al vencer (24 h sin refrescar). Sin fotos ni vectores biométricos.
- **El rol `cliente` no guarda nada** (recibe filas enmascaradas).
- **La cola de ingresos sigue sin guardar la cédula** (solo huella); el vínculo para «Deshacer» vive en memoria.
- **Regla de seguridad:** si la copia completa trae menos personas que la lista mínima, no se usa (se muestra la mínima con su aviso de siempre).
- **Editar sin red envía solo lo que cambió** (no pisa lo que otro equipo haya editado). Dejar un dato vacío, cambiar la cédula, la fecha de nacimiento y las firmas siguen pidiendo conexión.

## Piezas

| # | Pieza | Estado |
|---|-------|--------|
| 1 | Copia completa cifrada + lista sin red con todos los datos + editar viendo los valores guardados | **Hecha (rama)** |
| 2 | Quitar un registro sin red, crear persona con todos los campos, editar sin «formulario de persona» | Pendiente |
| 3 | Imprimir escarapela sin red (diseño y datos guardados; parámetros de impresión INAMOVIBLES intactos) | Pendiente |
| 4 | Entrega de inventario sin red | Pendiente |
| 5 | Dependientes y código de la persona sin red | Pendiente |
| 6 | Control de áreas sin red | Pendiente |
| 7 | Escáner de cédula sin red: librerías dentro del proyecto (`scripts/vendor_cedula_readers.sh`, hay que correrlo en un equipo con internet) y guardadas por el service worker | Pendiente |
| 8 | Comprobación en modo servidor local | Pendiente |
| 9 | Texto legal: el texto C''' de la auditora (política v1.1) dice que el dispositivo guarda solo nombre, categoría, estado y huella. Con esta función guarda más. **El texto lo cambia la auditora, no Claude**: pedirle la versión actualizada antes de producción. | Pendiente (Juan David) |

## Dónde está el código (pieza 1)

- `static/js/contingency.js`: `peopleSave`, `peoplePatch`, `peopleApply`, `peopleLoad`, `peopleMeta`.
- `static/js/directory.js`: `saveFullCopy`, `loadFromLocalCopy` (copia completa primero), `buildOfflinePersonEditModal` (valores reales con `__full`).
- Prueba: `tests/js/contingency_full_check.js`.
