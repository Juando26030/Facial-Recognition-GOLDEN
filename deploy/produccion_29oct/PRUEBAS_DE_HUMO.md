# Pruebas de humo en producción (después de desplegar, 29-oct-2026)

Datos **ficticios**, con un evento **PRUEBA-SALIDA** que se crea para esto y se **finaliza al terminar** (así la purga y el conteo de eventos no se ven afectados). Nada de personas reales; **no tocar** a ninguna persona real. Hacerlas desde el computador con la Brother (Windows + **Chrome normal**, con el cuadro de impresión visible) y, si se puede, un celular Android.

1. **Login:** entrar a `https://app.golden-eventos.com` con una cuenta super_admin. Debe abrir el panel sin errores.
2. **Privacidad:** abrir `/privacidad` (política vigente) y un enlace de autorización de prueba; deben verse sin errores.
3. **Evento PRUEBA-SALIDA:** crear el evento, cargar 3 personas ficticias, ponerlo en curso.
4. **Registro:** en «Registro», buscar por cédula y **Acreditar** a una persona ficticia; debe quedar «Registrado».
5. **Impresión normal, vertical:** con la compartida APAGADA, imprimir una escarapela vertical (62×100 mm). Debes ver: el cuadro de Chrome con papel 62 × 99,8 mm, sin fecha, ruta, título ni «1/1» en la vista previa; la etiqueta centrada.
6. **Impresión normal, horizontal:** cambiar la plantilla a horizontal (100×62 mm) con el recorte por defecto e imprimir. Debes ver: tira de unos 9 cm con el texto **centrado a lo largo de la tira**, sin textos de Chrome.
7. **Windows sin poder abrir la impresora:** la barra debe verse **amarilla** con la explicación, sin botón «Conectar impresora».
8. **Compartida:** encender «Impresión compartida»; con un celular/tablet Android conectado a la impresora y otro equipo pidiendo la escarapela: sale **una sola vez**; lo que no sale queda en la **Cola**; «Imprimir pendientes» funciona.
9. **Sesiones:** con una cuenta digitador, iniciar sesión en dos navegadores: la primera debe cerrarse con aviso; un admin no tiene límite.
10. **Contingencia:** con el Registro de PRUEBA-SALIDA abierto y la **lista cargada** en el dispositivo (la barra muestra la lista local «N de N»), **corta la red**, registra a una persona ficticia **sin conexión**, **vuelve la red** y comprueba que **sincroniza** y que la lista local sigue mostrando **N de N**.
11. **Exportar:** en «Clientes», en el evento PRUEBA-SALIDA, **📦 Exportar** (sin biometría). Debes ver: barra de avance, «Paquete listo» con conteos y el botón de descarga; baja un `.zip`. Bórralo de tu computador después.
12. **Importar (simulacro y de verdad):** en el mismo cliente, **📥 Importar evento**, sube ese `.zip`. Debes ver: «Paquete válido»; con el mismo código y nombre, el aviso de conflicto («Ya existe un evento…»); con código `PRUEBA-COPIA` y nombre nuevo, el **simulacro** (no escribe nada) y luego **Importar de verdad**: informe «Origen vs Destino» con ✅ iguales (las personas aparecen como «ya existían»: es el mismo cliente). El evento nuevo queda en «Creado».
13. **`/sistema`:** sin rojos (base, almacenamiento, cola, Job horario).
14. **Cierre:** apagar la compartida, **finalizar PRUEBA-SALIDA y PRUEBA-COPIA** y correr `bash deploy/produccion_29oct/verificar_despues.sh <hash de main>` (0 errores en los registros).

Si algo falla: criterio y pasos de vuelta atrás en `docs/13_RUNBOOK_PRODUCCION.md`, sección del 29-oct.
