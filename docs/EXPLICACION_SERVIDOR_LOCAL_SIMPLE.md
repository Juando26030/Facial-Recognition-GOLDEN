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

## Cómo publicar el instalador (lo hace un administrador)
El botón de descarga aparece solo cuando el archivo del instalador está guardado en el almacenamiento de GoldenWeb. Hay que **construirlo** y **subirlo**; se repite cada vez que cambie la versión de producción. La misma guía, paso a paso, está en **Configuración → Servidor local → «Cómo publicar el instalador»** (solo la ven administradores).

**Qué se necesita:** acceso al repositorio de GitHub (camino A) o un computador con Windows con internet (camino B); la herramienta de Google Cloud (`gcloud`) con tu cuenta de Golden; y el nombre del almacenamiento de la app (en `deploy/gcp/config.sh`: `APP_BUCKET` y `APP_PREFIX`; abajo `BUCKET` y `PREFIJO`).

**Paso 1 · Construirlo.**
- *Camino A, sin Windows (GitHub):* en GitHub, Actions → «Instalador de Windows (servidor local)» → «Run workflow» → escribe la versión (ejemplo `2026.11.10`) → espera 20 a 30 minutos → descarga el archivo comprimido `golden-local-windows`; dentro está `GoldenLocal-Setup-2026.11.10.exe`. Con comandos:
  ```
  gh workflow run instalador-windows.yml -f version=2026.11.10
  gh run watch
  gh run download -n golden-local-windows -D instalador
  ```
  (Gasta minutos de GitHub Actions; no corre solo, solo cuando lo pides.)
- *Camino B, en un Windows:* instala Git, Python 3.13 e Inno Setup 6. En PowerShell:
  ```
  git clone https://github.com/Juando26030/Facial-Recognition-GOLDEN.git
  cd Facial-Recognition-GOLDEN
  git checkout f5/integracion
  Set-ExecutionPolicy -Scope Process Bypass
  .\deploy\windows\build_installer.ps1 -Version 2026.11.10
  ```
  El archivo queda en `build\windows\out\GoldenLocal-Setup-2026.11.10.exe`.

**Paso 2 · Subirlo.** El nombre debe ser exactamente `GoldenLocal-Setup-<versión>.exe`.
```
gcloud auth login
gsutil cp GoldenLocal-Setup-2026.11.10.exe gs://BUCKET/PREFIJO/system/local-installer/
```
Si el entorno no usa prefijo, la ruta es `gs://BUCKET/system/local-installer/`. Sin comandos: en la consola web de Google Cloud → Cloud Storage → el almacenamiento → carpeta `system/local-installer` (créala si no existe) → arrastra el archivo.

**Paso 3 · Comprobar.**
1. `gsutil ls gs://BUCKET/PREFIJO/system/local-installer/` muestra el archivo.
2. Recarga Configuración → Servidor local: la tarjeta debe decir **«Disponible»** con la versión (antes decía «Aún no disponible»).
3. Pulsa «Descargar instalador para Windows» y confirma que baja el archivo.

Si hay varias versiones guardadas se ofrece la más alta; para retirar una, bórrala de esa carpeta. El otro archivo que genera la construcción (`golden-local-update-<versión>.zip` y su `.sha256`) es para «Actualizar ahora» y no va en esta carpeta (ver `docs/FASE_6_SERVIDOR_LOCAL.md`).

## Lo que falta (honesto)
- El instalador **todavía no se ha construido ni probado en un computador real**: hay que armarlo una vez en un Windows (instrucciones en `docs/FASE_6_SERVIDOR_LOCAL.md`, «Paso a paso para Juan David») y subir el archivo para que aparezca el botón en Configuración.
- Por ahora sirve con seguridad para eventos de **registro e ingresos**. Entregas de inventario, ruleta y turnos hechos en el servidor local aún no suben a internet, y el sistema **no deja pasar a internet** mientras haya algo así sin subir.
- Falta el ensayo con laptop, router y varios equipos reales (corte de luz y de internet incluidos).
