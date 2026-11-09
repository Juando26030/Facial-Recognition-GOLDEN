# Instalación del servidor local (Fase 6). La corre el instalador (GoldenLocal.iss) con permisos de administrador; también se puede volver a correr (es repetible: no pisa la base ni los secretos).
# Hace: carpetas, secretos, base PostgreSQL (servicio), migraciones, certificados HTTPS, servicios de Windows (app y actualizador), cortafuegos, energía y la primera copia de la base.
param([string]$ProductionUrl = '')
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Hay que ejecutarlo como administrador.' }

Write-Log '== Instalación del servidor local =='
foreach ($d in @($ConfigDir, $DataDir, $FilesDir, $UpdateDir, $BackupDir, $LogDir, $CertDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

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
Protect-File $EnvFile
$cfg = Read-EnvFile

# ---- 2. Dirección por la que se entra al servidor (se completa tras los certificados)
$ips = @(Get-LanAddresses)
$host_ = $env:COMPUTERNAME

# ---- 3. Certificados HTTPS (autoridad propia + certificado del servidor)
$serverPem = Join-Path $CertDir 'server.pem'
$needCert = -not (Test-Path $serverPem)
if (-not $needCert) { $left = & $Python -c "import sys; sys.path.insert(0, r'$ScriptsDir'); import gen_cert, pathlib; print(gen_cert.days_left(pathlib.Path(r'$serverPem')))"; if ([int]$left -lt 60) { $needCert = $true } }
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
function Invoke-AsNetworkService([string]$Exe, [string]$Args_, [string]$LogName) {
    $log = Join-Path $LogDir $LogName
    $act = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"`"$Exe`" $Args_ > `"$log`" 2>&1`""
    $pr = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\NETWORK SERVICE' -LogonType ServiceAccount -RunLevel Limited
    $name = "GoldenLocal-$LogName"
    Register-ScheduledTask -TaskName $name -Action $act -Principal $pr -Force | Out-Null
    Start-ScheduledTask -TaskName $name
    do { Start-Sleep -Seconds 1 } while ((Get-ScheduledTask -TaskName $name).State -eq 'Running')
    $code = (Get-ScheduledTaskInfo -TaskName $name).LastTaskResult
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    if ($code -ne 0) { throw "$Exe falló ($code); ver $log" }
}
if (-not (Test-Path (Join-Path $PgData 'PG_VERSION'))) {
    New-Item -ItemType Directory -Force -Path $PgData | Out-Null
    & icacls $DataDir /grant 'NT AUTHORITY\NETWORK SERVICE:(OI)(CI)F' | Out-Null
    $pwfile = Join-Path $ConfigDir 'pg.pw'
    Write-Utf8NoBom $pwfile $cfg['LOCAL_DB_PASSWORD']
    & icacls $pwfile /grant 'NT AUTHORITY\NETWORK SERVICE:R' | Out-Null
    Invoke-AsNetworkService (Join-Path $PgDir 'bin\initdb.exe') "-D `"$PgData`" -U golden --pwfile=`"$pwfile`" --auth=scram-sha-256 -E UTF8 --locale=C" 'initdb.log'
    Remove-Item $pwfile -Force
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
