# GoldenWeb 2.0 — Novedades de la versión del 28 de octubre de 2026

Producción queda igual que staging el 28-oct-2026 (código `79348da`). Lo que sigue es lo que **cambia para quien opera**.

## Para quien imprime (Brother QL-800) — parámetros inamovibles
- **Con impresión compartida APAGADA** (así viene cada evento): si el computador puede abrir la impresora por USB, imprime directo («Impresora conectada»); si no, usa la **ventana de impresión de Chrome**, con la **misma etiqueta** (recorte, giro y margen de Parámetros y de ⚙️).
- **La ventana de impresión sale limpia:** centrada y **sin** fecha, ruta, título ni «1/1» de Chrome, en etiqueta vertical y horizontal. La etiqueta sale en papel de **62 mm de ancho y mínimo ~10 cm de largo**: una etiqueta corta deja tira en blanco al final.
- **Windows con el controlador oficial de Brother:** Chrome no puede abrir la impresora por USB («Access denied»). La barra se ve **amarilla** y lo explica (se imprime con la ventana de Chrome; para compartir la impresora, usar un celular o tablet Android). Ya no hay barra roja ni botón «Conectar impresora» sin efecto.
- **Impresión compartida** (se enciende por evento): varios equipos imprimen en **una** impresora conectada a otro (celular o tablet Android); cada escarapela sale **una sola vez** y lo que no salió queda en la **Cola**. «Imprimir pendientes» en el equipo de la impresora.
- Cada equipo conserva sus ajustes (cinta, giro, margen, corte, espejo).

## Para el digitador (Registro)
- **«Registro touch»** en celular o tablet: tarjetas por persona con botones grandes (Acreditar, Imprimir, Editar). Teclado numérico para la cédula; se puede pegar una cédula.
- **No se acredita** a una persona con un campo obligatorio vacío: se abre «Editar persona» en el campo que falta. Quitar un registro funciona por todos los caminos.

## Cuentas y sesiones — **se nota**
- **Sesión única** (viene **encendida**): las cuentas que no son admin/super_admin solo pueden tener **una** sesión; entrar desde otro equipo cierra la anterior (un aviso lleva al inicio de sesión). Los admin no tienen límite. **Se apaga en Configuración.**
- **Cuenta «Puesto de impresión»** (casilla en la cuenta): un segundo inicio de sesión se rechaza mientras esté en uso; un administrador la libera.
- **Parámetros → Puestos de impresión:** cada puesto muestra o esconde el menú de impresión (Mostrar/Esconder) y puede ser «solo lector».
- Desplegar **no expulsa a nadie**: las sesiones activas siguen válidas.

## Para quien arma el evento
- La **procedencia** de cada persona (base, manual, autoregistro) queda registrada; las ya existentes se rellenan con lo que hay y el resto queda «Desconocido».

## Lo que NO cambia
- Textos de autorización y política de privacidad. No se recoge ningún dato personal nuevo.
- La **contingencia sin conexión sigue APAGADA en producción** (decisión de Juan David).
