# Pruebas de humo en producción (después de desplegar)

Datos **ficticios**, con un evento **PRUEBA-SALIDA** que se crea para esto y se **finaliza al terminar** (así la purga y el conteo de eventos no se ven afectados). Nada de personas reales; **no tocar** a ninguna persona real. Hacerlas desde el computador con la Brother (Windows + Chrome) y, si se puede, un celular Android.

1. **Login:** entrar a `https://app.golden-eventos.com` con una cuenta admin. Debe abrir el panel sin errores.
2. **Privacidad:** abrir `/privacidad` (política vigente 1.1) y un enlace de autorización de prueba; deben verse sin errores.
3. **Evento PRUEBA-SALIDA:** crear el evento, cargar 3 personas ficticias, ponerlo en curso.
4. **Registro:** en «Registro», buscar por cédula y **Acreditar** a una persona ficticia; debe quedar «Registrado».
5. **Impresión normal, vertical:** con la compartida APAGADA, imprimir una escarapela con la plantilla vertical (62×100 mm). Debes ver: centrada, **sin** fecha, ruta, título ni «1/1».
6. **Impresión normal, horizontal:** cambiar la plantilla a horizontal (100×62 mm) e imprimir. Debes ver: texto a lo largo de la cinta, centrado, sin textos de Chrome.
7. **Windows sin poder abrir la impresora:** la barra debe verse **amarilla** con la explicación, sin botón «Conectar impresora».
8. **Compartida:** encender «Impresión compartida» en el evento; con un celular/tablet Android conectado a la impresora y otro equipo pidiendo la escarapela: sale **una sola vez**; lo que no sale queda en la **Cola**; «Imprimir pendientes» funciona.
9. **Sesiones:** con una cuenta digitador, iniciar sesión en dos navegadores: la primera debe cerrarse con aviso; un admin no tiene límite.
10. **`/sistema`:** sin rojos (base, almacenamiento, cola, Job horario).
11. **Cierre:** apagar la compartida, **finalizar PRUEBA-SALIDA**, y correr `bash deploy/produccion_28oct/verificar_despues.sh <hash de main>` (0 errores en los registros).

Si algo falla: criterio y pasos de vuelta atrás en `docs/13_RUNBOOK_PRODUCCION.md` §7.
