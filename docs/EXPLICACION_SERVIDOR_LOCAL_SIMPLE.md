# El servidor local, explicado sencillo (para Juan David)

## Qué es
Es una **copia de GoldenWeb que vive en un computador del evento**. Tu equipo (digitadores, coordinadores, el quiosco) se conecta a ese computador con el wifi del lugar y trabaja igual que siempre: registrar, escanear, imprimir escarapelas. Como todo está en ese computador, **si se cae el internet, el evento sigue funcionando**.

Piénsalo como llevar la lista del evento en una carpeta física: aunque la oficina se quede sin luz, la carpeta está contigo. Solo que esta carpeta se actualiza sola cuando vuelve el internet.

## Qué se necesita
- Un computador portátil con **Windows 10 u 11**, 8 GB de memoria (un Intel i5 sirve).
- Un **router o wifi propio** para que los demás equipos se conecten al computador. No tiene que tener internet.
- **Internet solo al principio**, para instalar el programa y bajar el evento (en la oficina o en el hotel).
- Una cuenta de la empresa: coordinador, comercial, administrador, almacén o contabilidad. Los digitadores temporales y los clientes **no** lo preparan.
- **Sin reconocimiento facial.** En el servidor local se entra por cédula, código QR o búsqueda.

## Paso a paso
1. En GoldenWeb, entra a **Configuración → Servidor local** y pulsa **Descargar instalador para Windows**. (Si dice «Aún no disponible», el instalador todavía no se ha publicado; ver «Lo que falta» más abajo.)
2. En el computador del evento, con internet, abre el archivo con doble clic. Di «Sí» a los permisos y espera unos minutos. No hay que escribir comandos.
3. Entra con **tu mismo usuario y contraseña** de siempre. Las cuentas se copian de internet; la contraseña solo se puede cambiar en internet.
4. En la lista de eventos, elige el tuyo y pulsa **«Descargar a local»**. El evento baja completo (sin fotos de rostros).
5. El día del evento, conecta los demás equipos al mismo wifi y trabaja normalmente.
6. Al terminar, con internet, pulsa **«Pasar a internet»**. Todo lo hecho se sube y el evento vuelve a poder editarse en internet.

## Quién manda: el «arrendamiento» del evento
Para que nunca existan dos versiones distintas del mismo evento, **un evento solo se puede cambiar en un lugar a la vez**. Cuando lo bajas al servidor local, el evento queda «prestado» a ese computador: en internet se puede **mirar pero no cambiar**. Cuando pulsas «Pasar a internet», el préstamo se devuelve y vuelve a mandar internet. Es como llevarse una carpeta prestada de un archivo: mientras la tienes tú, nadie más la modifica.

## Qué pasa si no hay internet
- **Todo sigue funcionando** en el evento: registrar, escanear, imprimir.
- Cuando el computador encuentra internet, **sube solo lo que hizo**, más o menos cada 30 minutos.
- Si el internet nunca vuelve durante el evento, no pasa nada: se sube después, al llegar a la oficina o al hotel.
- El computador **no se apaga solo**; un turno puede ser de 6 a. m. a 6 p. m. o de noche. Solo se apaga a mano.

## Actualizaciones
Cuando internet cambie de versión, el servidor local avisa con una franja visible. Hay un botón **«Actualizar ahora»**: guarda una copia, actualiza y arranca de nuevo; si algo sale mal, vuelve solo a como estaba. Nunca lo hagas en medio de un turno.

## Lo que falta (honesto)
- El instalador **todavía no se ha construido ni probado en un computador real**: hay que armarlo una vez en un Windows (instrucciones en `docs/FASE_6_SERVIDOR_LOCAL.md`, «Paso a paso para Juan David») y subir el archivo para que aparezca el botón en Configuración.
- Por ahora sirve con seguridad para eventos de **registro e ingresos**. Entregas de inventario, ruleta y turnos hechos en el servidor local aún no suben a internet, y el sistema **no deja pasar a internet** mientras haya algo así sin subir.
- Falta el ensayo con laptop, router y varios equipos reales (corte de luz y de internet incluidos).
