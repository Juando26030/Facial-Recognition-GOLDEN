# Instalación del servidor local (Fase 6). La corre el instalador (GoldenLocal.iss) con permisos de administrador; también se puede volver a correr (es repetible: no pisa la base ni los secretos).
# Hace: carpetas, secretos, base PostgreSQL (servicio), migraciones, certificados HTTPS, servicios de Windows (app y actualizador), cortafuegos, energía y la primera copia de la base.
param([string]$ProductionUrl = '')
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Stop'
# Todo error queda escrito en logs\instalador.log (la ventana del instalador se cierra y el error se perdía)
trap { Write-Log "ERROR: $($PSItem.Exception.Message) (línea $($PSItem.InvocationInfo.ScriptLineNumber))"; throw }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Hay que ejecutarlo como administrador.' }

Write-Log '== Instalación del servidor local =='
foreach ($d in @($ConfigDir, $DataDir, $FilesDir, $UpdateDir, $BackupDir, $LogDir, $CertDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# ---- Requisitos de Windows (Visual C++, red, puerto); falla con un mensaje claro si el equipo no sirve
$env:GOLDEN_SILENT = '1'
& (Join-Path $ScriptsDir 'prereq.ps1'); if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw 'Los requisitos de Windows no se cumplieron (ver logs\instalador.log)' }

# ---- 0a. Instalador liviano (20-nov-2026): el .exe no trae el código de la app; si el asistente dejó una llave de producto, se reclama y se baja la aplicación (scripts\download-app.ps1).
# Sin llave y sin app instalada no hay nada que instalar: se detiene con un mensaje claro.
$installRequest = Join-Path $ConfigDir 'install-request.json'
if (Test-Path $installRequest) { & (Join-Path $ScriptsDir 'download-app.ps1'); if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw 'No se pudo descargar la aplicación (ver logs\instalador.log)' } }
elseif (-not (Test-Path (Join-Path $AppDir 'app\main.py'))) { throw 'Este instalador necesita una llave de producto. Vuelve a ejecutarlo y escríbela cuando la pida (te la da un administrador de Golden).' }

# ---- 0. Permisos de la carpeta (F5-9 A-03). Una carpeta nueva en C:\ hereda «Modificar» para Usuarios autenticados: cualquier cuenta de Windows del equipo podría cambiar
# los scripts o la app que corren como SYSTEM, o dejar una petición de actualización. Se corta la herencia: SYSTEM y Administradores, control total; Usuarios solo leen y
# ejecutan los programas (app, python, pgsql, tools, scripts) y la carpeta de certificados (el .cer para los celulares; las llaves tienen sus propios permisos).
# NetworkService (PostgreSQL) escribe en data\ (la base) y en logs\. Nadie más lee data\, backups\ ni config\ (datos personales y secretos).
# Se usan los identificadores universales (SID) y no los nombres: en Windows en español «Administrators»/«Users» se llaman «Administradores»/«Usuarios» y icacls no los encuentra.
& icacls $Root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron fijar los permisos de la carpeta de instalación' }
foreach ($d in @($AppDir, $PyDir, $PgDir, $ToolsDir, $ScriptsDir, $CertDir)) { if (Test-Path $d) { & icacls $d /grant '*S-1-5-32-545:(OI)(CI)RX' | Out-Null } }
& icacls $DataDir /grant '*S-1-5-20:(OI)(CI)F' | Out-Null
& icacls $LogDir /grant '*S-1-5-20:(OI)(CI)M' | Out-Null

# ---- 1. Configuración y secretos (solo la primera vez; una reinstalación conserva la clave y la base)
if (-not (Test-Path $EnvFile)) {
    $defaults = Read-EnvFile (Join-Path $ScriptsDir 'defaults.env')
    Set-EnvKey 'SECRET_KEY' (New-RandomSecret 32)
    Set-EnvKey 'LOCAL_DB_PASSWORD' (New-RandomSecret 16)
    Set-EnvKey 'ENVIRONMENT' 'local'
    Set-EnvKey 'LOCAL_SERVER' '1'
    Set-EnvKey 'APP_MODE' 'web'
    Set-EnvKey 'STORAGE_BACKEND' 'local'
    Set-EnvKey 'STORAGE_LOCAL_DIR' $FilesDir
    Set-EnvKey 'JOBS_BACKEND' 'db'
    Set-EnvKey 'JOBS_WORKER' 'on'
    Set-EnvKey 'BULK_BACKEND' 'thread'
    Set-EnvKey 'CONTINGENCY_ENABLED' '1'
    Set-EnvKey 'LOCAL_UPDATE_DIR' $UpdateDir
    $url = if ($ProductionUrl) { $ProductionUrl } else { $defaults['PRODUCTION_URL'] }
    Set-EnvKey 'PRODUCTION_URL' $url
    $dbpw = (Read-EnvFile)['LOCAL_DB_PASSWORD']
    Set-EnvKey 'DATABASE_URL' "postgresql://golden:$dbpw@127.0.0.1:$PgPort/golden"
    Write-Log 'Configuración creada (config\local.env)'
}
# Llave de producto: queda en local.env como SERVER_KEY (es el ID del servidor) junto con la identificación de esta instalación. Una llave DISTINTA a la anterior (reinstalar en un equipo deshabilitado) limpia el bloqueo
# y el vínculo viejo para que se vuelva a vincular con la llave nueva.
if (Test-Path $installRequest) {
    $rq = Get-Content $installRequest -Raw -Encoding UTF8 | ConvertFrom-Json
    $before = Read-EnvFile
    if ("$($before['SERVER_KEY'])" -ne "$($rq.key)") { Set-EnvKey 'NODE_TOKEN' ''; Set-EnvKey 'SERVER_DISABLED' '' }
    Set-EnvKey 'SERVER_KEY' "$($rq.key)"
    Set-EnvKey 'INSTALLATION_ID' "$($rq.installation_id)"
    Remove-Item $installRequest -Force
}
Protect-File $EnvFile
$cfg = Read-EnvFile

# ---- 2. Dirección por la que se entra al servidor (se completa tras los certificados)
$ips = @(Get-LanAddresses)
$host_ = $env:COMPUTERNAME

# ---- 3. Certificados HTTPS (autoridad propia + certificado del servidor)
$serverPem = Join-Path $CertDir 'server.pem'
$needCert = -not (Test-Path $serverPem)
if (-not $needCert) { $left = & $Python -c "import sys; sys.path.insert(0, r'$ScriptsDir'); import gen_cert, pathlib; print(gen_cert.days_left(pathlib.Path(r'$serverPem')))"; if ([int]$left -lt 60) { $needCert = $true }; if ("$(& $Python (Join-Path $ScriptsDir 'gen_cert.py') --missing $serverPem @ips)".Trim()) { $needCert = $true } }
if ($needCert) {
    & $Python (Join-Path $ScriptsDir 'gen_cert.py') $CertDir $host_ @ips
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron crear los certificados' }
    Import-Certificate -FilePath (Join-Path $CertDir 'GoldenLocal-CA.cer') -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Write-Log 'Certificados creados y autoridad instalada en Windows'
}
Protect-File (Join-Path $CertDir 'server.key'); Protect-File (Join-Path $CertDir 'ca.key')
$primary = if ($ips.Count -gt 0) { $ips[0] } else { 'localhost' }
Set-EnvKey 'PUBLIC_BASE_URL' "https://${primary}:$AppPort"

# ---- 4. Base de datos PostgreSQL como servicio (corre como NetworkService: Postgres no arranca con permisos de administrador)
if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
    # initdb se corre DIRECTO (no en una tarea programada: en algunos equipos la tarea se queda en «Queued» y nunca corre, y se daba por buena sin haber creado la base).
    # initdb de Windows suelta solo los privilegios de administrador (token restringido); después se le da el control de la carpeta a NetworkService, que es quien corre el servicio.
    if (Test-Path $PgData) { Remove-Item $PgData -Recurse -Force }      # una carpeta a medias (sin PG_VERSION) impide crear la base
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    $pwfile = Join-Path $ConfigDir 'pg.pw'
    Write-Utf8NoBom $pwfile $cfg['LOCAL_DB_PASSWORD']
    # initdb corre con un token SIN el grupo Administradores: no puede leer la clave ni escribir en la carpeta que creó un administrador. Acceso temporal para Usuarios (se retira al terminar).
    & icacls $pwfile /grant '*S-1-5-32-545:R' | Out-Null
    & icacls $PgData /grant '*S-1-5-32-545:(OI)(CI)F' | Out-Null
    $initOut = & (Join-Path $PgDir 'bin\initdb.exe') -D $PgData -U golden --pwfile=$pwfile --auth=scram-sha-256 -E UTF8 --locale=C 2>&1
    $initCode = $LASTEXITCODE
    Remove-Item $pwfile -Force -ErrorAction SilentlyContinue
    Set-Content -Path (Join-Path $LogDir 'initdb.log') -Value ($initOut | Out-String) -Encoding UTF8
    if ($initCode -ne 0 -or -not (Test-Path (Join-Path $PgData 'PG_VERSION'))) { throw "No se pudo crear la base de datos (initdb código $initCode); ver logs\initdb.log" }
    & icacls $PgData /reset /T /C /Q | Out-Null                              # quita el acceso temporal: la carpeta vuelve a heredar solo SYSTEM, administradores y NetworkService
    & icacls $PgData /grant '*S-1-5-20:(OI)(CI)F' /T /C /Q | Out-Null
    $conf = Join-Path $PgData 'postgresql.conf'
    Add-Content $conf "`nport = $PgPort`nlisten_addresses = 'localhost'`nshared_buffers = 256MB`nmax_connections = 60`nwork_mem = 8MB`nlog_destination = 'stderr'`nlogging_collector = on`nlog_directory = '$($LogDir -replace '\\','/')'`nlog_filename = 'postgres-%a.log'`nlog_truncate_on_rotation = on"
    Write-Log 'Base de datos inicializada'
}
if (-not (Get-Service $SvcPg -ErrorAction SilentlyContinue)) {
    & (Join-Path $PgDir 'bin\pg_ctl.exe') register -N $SvcPg -D $PgData -S auto -U 'NT AUTHORITY\NetworkService'
    & sc.exe failure $SvcPg reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
}
Start-Service $SvcPg
$ok = $false; foreach ($i in 1..30) { & (Join-Path $PgDir 'bin\pg_isready.exe') -h 127.0.0.1 -p $PgPort | Out-Null; if ($LASTEXITCODE -eq 0) { $ok = $true; break }; Start-Sleep -Seconds 2 }
if (-not $ok) { throw 'La base de datos no arrancó (ver logs\)' }
$env:PGPASSWORD = $cfg['LOCAL_DB_PASSWORD']
$exists = & (Join-Path $PgDir 'bin\psql.exe') -h 127.0.0.1 -p $PgPort -U golden -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='golden'"
if ("$exists".Trim() -ne '1') { Invoke-Pg 'createdb' @('golden') }

# ---- 5. Migraciones (deja la base en la versión de este instalador)
Import-GoldenEnv
Push-Location $AppDir
try { & $Python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Las migraciones fallaron' } } finally { Pop-Location }
Write-Log 'Migraciones aplicadas'

# ---- 6. Servicios de Windows (WinSW): la app y el actualizador. Arranque automático y reinicio si se caen.
foreach ($svc in @($SvcApp, $SvcUpd)) {
    Copy-Item (Join-Path $ToolsDir 'WinSW.exe') (Join-Path $ToolsDir "$svc.exe") -Force
    Copy-Item (Join-Path $ScriptsDir "$svc.xml") (Join-Path $ToolsDir "$svc.xml") -Force
    if (-not (Get-Service $svc -ErrorAction SilentlyContinue)) { & (Join-Path $ToolsDir "$svc.exe") install }
    & sc.exe failure $svc reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
}
Start-Service $SvcApp
Start-Service $SvcUpd

# ---- 7. Cortafuegos: solo la red local (no internet) puede entrar al puerto de la app
Get-NetFirewallRule -DisplayName 'Golden Local (HTTPS)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'Golden Local (HTTPS)' -Direction Inbound -Protocol TCP -LocalPort $AppPort -Action Allow -Profile Any -RemoteAddress LocalSubnet | Out-Null

# ---- 8. Energía: nunca se duerme ni se apaga solo
& (Join-Path $ScriptsDir 'power.ps1')

# ---- 9. Primera copia de la base y resumen para quien instala
try { $b = Backup-Database 'instalacion'; Write-Log "Copia inicial: $b" } catch { Write-Log "No se pudo hacer la copia inicial: $_" }
$info = "Servidor local instalado.`r`nEntrar desde este equipo: https://localhost:$AppPort`r`nDesde otros equipos de la red: https://${primary}:$AppPort`r`nPara los celulares: instalar el archivo $CertDir\GoldenLocal-CA.cer (ver docs/17_SERVIDOR_LOCAL.md)."
Set-Content -Path (Join-Path $Root 'LEEME-GOLDEN-LOCAL.txt') -Value $info -Encoding UTF8
Write-Log $info
Write-Log '== Instalación terminada =='
