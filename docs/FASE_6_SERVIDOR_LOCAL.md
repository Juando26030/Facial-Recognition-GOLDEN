# Fase 6 · Operación sin red — decisiones y plan (9-nov-2026)

Alcance del plan maestro (docs/29 §11): servidor local con sincronización (docs/17); B8 R2–R5 (foto y consentimiento sin red, edición sin red, PIN opcional, dos dispositivos); pruebas en dispositivos reales.
**Listo cuando:** un evento completo se atiende sin internet y al conectarse queda igual en la nube.

## Respuestas de Juan David a las preguntas abiertas de docs/17 (9-nov-2026)
1. **Laptops servidoras:** procesador Intel i5, 8 GB de RAM, Windows 10 u 11 (en promedio).
2. **Reconocimiento facial:** en eventos locales **NO** se maneja si es complicado. → El servidor local corre el servicio «web» (sin `face_recognition`/dlib), solo cédula, QR y búsqueda. Esto además baja el consumo de memoria.
3. **Duración:** un día no pasa de **12 horas**; puede haber varios días de ~12 h cada uno. → Hay noches entre días: el servidor se apaga y se enciende; los datos están en un volumen persistente y se sincroniza apenas haya internet (p. ej. en el hotel).
4. **Quién prepara el servidor:** cualquier cuenta de la empresa (admin, coordinador, comercial, bodega/almacén…) **excepto** los digitadores temporales (tampoco clientes). → El paso de preparación debe ser de un clic y a prueba de errores.

## Decisiones derivadas
- **Opción A (Docker) en modo «web» + PostgreSQL.** Con 8 GB, Docker Desktop (~2–4 GB) + Postgres (1 GB) + app (2 GB) cabe si no hay facial. Plan B (nativo en Windows) solo si Docker falla en las laptops reales.
- **La imagen no se compila en la laptop** (dlib tarda mucho y necesita internet): se construye en la nube y viaja como archivo (`docker save`/`docker load`) o ya viene precargada. Hay que preparar la laptop ANTES de salir (con internet).
- **Permiso de preparación:** `coordinador`, `comercial`, `admin`, `super_admin`, `almacen`, `contabilidad` (rol principal o sumado). Hoy exportar/importar eventos es solo Super Admin (docs/18): para el servidor local se abre a estos roles **sobre eventos a los que pertenecen** (no a todo el sistema).
- **Un solo escritor por evento** (arrendamiento): mientras el evento está en un servidor local, la nube lo marca y lo muestra en solo lectura.
- **Subida reusando lo que ya es idempotente:** el servidor local reenvía sus registros a la nube con los endpoints que ya existen (`access-logs/sync`, `outbox/sync`, identificador único por registro), con un token por nodo revocable. Reenviar nunca duplica.
- B8 R2–R5 (bandeja de salida en cada navegador) siguen siendo la red de seguridad de cada equipo; R4 (PIN y protección del dispositivo) va antes que R2 (foto y consentimiento).

## Etapas (en orden) y estado
| Etapa | Qué | Estado |
|---|---|---|
| **E0 · Kit del servidor** | Instalador nativo de Windows (doble clic, sin Docker; `deploy/windows/`) + kit Docker de respaldo (`deploy/local/`) | **Programado, sin probar** (no hay Windows ni laptop aquí). Lo construye y prueba Juan David con el paso a paso de «Actualizar e instalar» |
| **E1 · Paquete y permiso** | Lista de TODOS los eventos de la nube en el servidor local + «Descargar a local» en un paso (sin biometría); exportar abierto a roles de empresa; importar solo con `LOCAL_SERVER=1` | **Programado, sin probar** (suite bloqueada hasta el 11-nov 14:05). La copia importada fija `cloud_event_id` y `sync_package_at` |
| **E2 · Arrendamiento + subida** | «En servidor local» (solo lectura en la nube), token por nodo (0112), subida cada ~30 min, «Pasar a internet» solo con 0 pendientes, panel `/sincronizacion`, cuentas y contraseñas nube→local, «Actualizar ahora» | **Programado, sin probar** (misma razón). El reloj de 30 min también refresca cuentas |
| **E3 · R4 y R2** | PIN opcional / exportación de emergencia; foto y consentimiento sin red | Por programar |
| **E4 · R3 y R5** | Edición sin red con conflictos; dos dispositivos | Por programar |
| **E5 · Dispositivos reales** | Ensayo con laptop i5/8 GB, router y 3–4 equipos; corte de energía y de red; evento simulado de ~12 h | Necesita hardware y a Juan David |

## Lo que NO puedo verificar yo
Nada de esta fase se prueba sin una laptop real con Docker y un router: el kit es un borrador razonado, no probado. Lo programable (permisos, arrendamiento, subida) lleva pruebas automáticas; lo físico lo hacemos juntos en E5.

## Flujo de uso decidido por Juan David (9-nov-2026, 13:49)
1. Los eventos se crean en la **nube** (producción).
2. El servidor local, **conectado a internet**, muestra la **lista de TODOS los eventos** como en producción (por clientes, por eventos y por calendario), pero **sin descargar su información**.
3. Al abrir un evento aparecen sus opciones de siempre (ingresar, editar…) y además **«Descargar a local»**: el evento baja completo (como exportar de la nube e importar en el local, pero en un solo paso).
4. También se puede hacer **a mano** (exportar en la nube, importar en el local).
5. Cada vez que el servidor tiene internet **sube lo que tenga, cada ~30 minutos**, como una copia en producción.
6. **Instalación:** un archivo que se abre con doble clic e instala TODO (incluida la base de datos), sin Docker ni comandos.
7. El servidor **no se apaga solo nunca**: un turno puede durar de 6 a.m. a 6 p.m. o de 6 p.m. a 6 a.m. y se pueden editar más de 12 horas; solo se apaga a mano. (Las «12 horas» eran solo la duración típica del día.)

## Aclaraciones de Juan David (9-nov-2026, 13:54) — decisiones firmes
1. **Solo lectura en la nube mientras el evento está en local**, pero debe poder **volver a internet** cuando se quiera: la acción «Pasar a internet» **sincroniza lo del local hacia la nube** y deja el evento editable otra vez en la nube (y el local lo suelta).
2. **Cuentas:** se entra al local con el **mismo usuario y contraseña de la nube**. Cada vez que el servidor se conecta, **actualiza las cuentas** (cambios de contraseña, altas, bajas, roles, desactivaciones) para que **nunca queden contraseñas distintas** en el servidor y en internet. **DECIDIDO (13:55): las contraseñas SOLO se cambian en la nube y la nube predomina; en el servidor local el cambio de contraseña está deshabilitado** (el local solo recibe lo que viene de la nube).
3. **Devolver** = **sincronizar con la nube** (misma acción de arriba): sube todo lo pendiente y libera el evento.
4. **Quién puede poner en local o subir:** cualquier coordinador (y los demás roles de la lista) sobre **cualquier evento**, no solo los suyos. (Reemplaza «solo sus eventos» de la etapa E1.)
5. **Instalación:** el camino que sea mejor, con la condición de que quien instale **no use comandos ni cosas complejas** (personas sin conocimientos de sistemas): doble clic, asistente, listo. Se adopta la **instalación directa en Windows sin Docker**.
6. **Actualización y versión:** la estructura debe dejar **fácil actualizar los servidores locales** cuando cambie producción, y **el servidor local avisa si su versión no es la de producción**.

## Regla de cuentas (Juan David, 9-nov-2026 14:29)
Los **digitadores temporales y las cuentas de cliente se crean SIEMPRE en la nube** antes de llevar el evento al local. El servidor local **nunca crea cuentas**: así la sincronización de cuentas nube→local no las desactiva. Las contraseñas solo se cambian en la nube.

## Diseño de actualización y versión (nuevo)
- Cada servidor local conoce su **versión** (commit y revisión de migraciones, como ya expone la nube) y, al tener internet, la compara con la de producción (`/health` o un endpoint de versión).
- Si difiere: **franja visible y permanente** («Este servidor tiene la versión X; producción tiene Y») y, según la diferencia, el sistema **recomienda o exige** actualizar. Una subida a la nube con versión incompatible se rechaza con un mensaje claro (nunca se mezclan esquemas distintos).
- **Actualizar = un botón** («Actualizar ahora»): descarga el paquete de la versión de producción, para el servicio, aplica el cambio y las migraciones de la base local, y vuelve a arrancar; **nunca en medio de un turno sin confirmar** y siempre con copia previa de la base local.
- El instalador y el paquete de actualización salen del **mismo proceso de publicación** que producción: así no hay dos versiones que mantener.

## Cuentas del servidor local (agente C, 9-nov-2026)
- **La nube manda; el local nunca sube cuentas.** `GET /api/node/accounts?since=<versión>` (cabecera `X-Node-Token`, `require_node` de `app/node_auth.py`; sin ese módulo el endpoint queda cerrado con 503) entrega empresas usadas y TODAS las cuentas con el HASH de la contraseña (nunca la contraseña) y una versión (huella SHA-256 de todo lo sincronizable). Si el local ya tiene esa versión responde `{unchanged: true}`. No lleva sesiones, intentos fallidos ni bloqueos.
- **Local (`app/account_sync.py`)**: `run_once(db)` pide a `PRODUCTION_URL` con `NODE_TOKEN`, verifica la huella, aplica TODO en una transacción (alta, actualización por `username`, rol, correo, activo, contraseña) y guarda la versión en `app_settings`. Lo que ya no está en la nube se **desactiva y archiva** (no se borra: hay llaves que le apuntan). Un cambio sube `session_epoch` de esa cuenta (cierra sus sesiones abiertas). Se niega a aplicar una respuesta dañada o sin ninguna cuenta activa. Sin red o sin configuración devuelve `{ok: False}`, nunca lanza. **Quién lo llama**: el ciclo de sincronización (~30 min) y al conectarse; no se registró como trabajo de la cola para no tocar `GENERAL_KINDS` (lo decide quien arme el ciclo).
- **Contraseñas solo en la nube** (`LOCAL_SERVER=1`, `app/localmode.py`): 403 «La contraseña solo se cambia en la nube» en cambiar contraseña, «olvidé mi contraseña», enlace de restablecer, restablecer la de otra cuenta y crear cuentas; el ingreso ya no obliga a cambiarla (`must_change_password` se ignora en el local, si no el usuario quedaría atrapado). Las pantallas no muestran el botón (Configuración, login, Staff).
- **Sin migración propia** (la versión usa `app_settings`): `0113_account_sync` no hizo falta.
- **Decidido (Juan David, 14:29):** digitadores temporales y cuentas de cliente se crean SIEMPRE en la nube antes de llevar el evento; el local nunca crea cuentas (ver «Regla de cuentas»).

## Actualizar e instalar (agente D, 9-nov-2026)
**Hecho (sin probar en Windows; las pruebas pytest no corren aquí, solo compilación, ruff y la lógica pura):**
- **«Actualizar ahora»**: `app/local_update.py` + `/api/ops/update` (POST), `/api/ops/update-status`, `/api/ops/update-manifest` (lo publica producción) + botón en la franja de versión (`static/js/version-banner.js`). La app **no se actualiza sola**: valida y deja `update-request.json`; el servicio `GoldenLocalUpdater` lo recoge. Reglas: solo `LOCAL_SERVER=1`; solo paquete por HTTPS con huella SHA-256; con un turno en marcha (evento «En proceso» + ingresos en los últimos 15 min) responde 409 `shift_active` y la pantalla pide una **segunda confirmación** más fuerte; roles: los mismos del arrendamiento.
- **Pasos del actualizador** (`deploy/windows/run-update.ps1`, cada uno visible en pantalla): copia de la base (`pg_dump -Fc` a `backups\`) → descarga y verificación de huella → cambio de carpeta `app\` (la anterior queda en `app.prev`) → piezas nuevas de Python si cambió `requirements-local.txt` → migraciones → reinicio y comprobación de `/health`. Si falla antes de tocar algo: «error», nada cambia. Si falla después: **vuelve a los archivos anteriores y restaura la base desde la copia** («rolledback»).
- **Instalador de doble clic** (`deploy/windows/`): `GoldenLocal.iss` (Inno Setup) + `install.ps1` (carpetas, secretos aleatorios, PostgreSQL como servicio, migraciones, certificados, servicios WinSW `GoldenLocalApp` y `GoldenLocalUpdater`, cortafuegos solo red local, energía, copia inicial), `uninstall.ps1` (NO borra datos ni copias), `power.ps1` (nunca suspende ni apaga; tapa cerrada no hace nada; Windows Update no reinicia solo), `gen_cert.py` (autoridad propia «Golden Local CA» + certificado del servidor con nombre del equipo e IP; la autoridad se conserva al renovar), `make_requirements.py` (sin dlib/face_recognition/gunicorn), `build_installer.ps1` (arma todo en una máquina Windows) y `.github/workflows/instalador-windows.yml` (**solo manual**, no corre solo, no publica; usa minutos de Actions, no se tocó la facturación).
- Todo vive en `C:\GoldenLocal` (app, python, pgsql, tools, scripts, config, data, backups, logs, certs). La base escucha solo en `127.0.0.1:5433`. Copia diaria a las 3:00 a. m. (se conservan 14).

**Paso a paso para Juan David** (en un computador Windows con internet, Python 3.13 y [Inno Setup 6](https://jrsoftware.org/isinfo.php)):
1. `git checkout f6/d-instalador` (o la rama integrada) y en PowerShell: `.\deploy\windows\build_installer.ps1` → deja en `build\windows\out\` el `GoldenLocal-Setup-<versión>.exe`, el `golden-local-update-<versión>.zip` y su `.sha256`.
2. Confirmar la dirección de producción en `deploy\windows\defaults.env` (`PRODUCTION_URL`).
3. Instalar en un portátil de prueba: doble clic en el `.exe` → «Sí» a los permisos de administrador → esperar unos minutos → abre `https://localhost:8443`.
4. Para los celulares: copiar `C:\GoldenLocal\certs\GoldenLocal-CA.cer` al celular e instalarlo como certificado de confianza (Android: Ajustes → Seguridad → Instalar certificado → «Certificado de CA»; iPhone: abrir el archivo → Perfil instalado → Ajustes → General → Información → Ajustes de confianza de certificados).
5. Para que «Actualizar ahora» funcione: subir el `.zip` a un lugar HTTPS (un bucket que Juan David crea; yo no creo recursos de nube) y poner en el servicio de producción `UPDATE_PACKAGE_URL` y `UPDATE_PACKAGE_SHA256` (el valor del `.sha256`). Cada publicación de producción debe repetir los pasos 1 y 5 para que el paquete corresponda a la misma versión.

**NO se pudo probar aquí (no hay Windows ni PostgreSQL de Windows):** nada de los `.ps1`, el `.iss` ni `build_installer.ps1` se ha ejecutado; los hallazgos probables del primer intento real: (a) que alguna dependencia de `requirements-local.txt` no tenga rueda para Python 3.13 en Windows (el build usa `--only-binary`); (b) permisos de la tarea que corre `initdb` como NetworkService; (c) ruta de PostgreSQL EDB (nombre del zip por versión; se fija en `-PostgresVersion`); (d) arranque de uvicorn con 2 trabajadores y HTTPS en Windows; (e) las huellas de las descargas (el build las imprime para fijarlas). **Dependencia de otro frente:** las cuentas (mismo usuario y contraseña de la nube) las sincroniza el trabajo de sincronización; el instalador no crea usuarios, así que hasta que exista no se puede entrar al servidor recién instalado. Locale de la base: `C` (sin reglas de ordenamiento de Windows).
