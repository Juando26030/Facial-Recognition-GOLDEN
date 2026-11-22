# Borrado de los DATOS del servidor local antes de devolver, prestar o dar de baja el portátil (revisión de seguridad 22-nov-2026).
# El desinstalador (uninstall.ps1) NO borra la base, las copias ni la configuración a propósito (si el evento no se subió a la nube, se perdería). Este script sí:
# detiene los servicios y elimina la base de datos (data\pgdata), los archivos del evento (data\files), las copias (backups\), los registros (logs\), los secretos y la
# vinculación (config\local.env: SECRET_KEY, LOCAL_DB_PASSWORD, NODE_TOKEN, SERVER_KEY) y las llaves de los certificados (certs\). Además quita la autoridad «Golden Local CA»
# de Windows. Con -Overwrite sobrescribe el espacio libre del disco (cipher /w) para que lo borrado no se pueda recuperar con herramientas de rescate (tarda: minutos u horas).
#
# ANTES de correrlo: en Sincronización, «Pasar a internet» en cada evento (0 pendientes) y deshabilitar la llave del servidor en Configuración › Servidor local (si no se va a usar más).
# Uso (PowerShell como administrador):  powershell -NoProfile -ExecutionPolicy Bypass -File C:\GoldenLocal\scripts\borrar-datos.ps1 [-Overwrite] [-Yes]
param([switch]$Overwrite, [switch]$Yes)
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $(if ($Overwrite) { '-Overwrite' })"; exit 0
}
Write-Host 'Este paso ELIMINA la base de datos local, los archivos de los eventos, las copias de seguridad, los registros y los secretos de este servidor.' -ForegroundColor Yellow
Write-Host 'Lo que no se haya subido a la nube («Pasar a internet» con 0 pendientes) se pierde para siempre.' -ForegroundColor Yellow
if (-not $Yes) {
    $ans = Read-Host 'Escribe BORRAR (en mayúsculas) para continuar'
    if ($ans -cne 'BORRAR') { Write-Host 'Cancelado: no se borró nada.'; exit 1 }
}
Write-Log '== Borrado de datos del servidor local (devolución del equipo) =='
foreach ($svc in @($SvcUpd, $SvcApp, $SvcPg)) {
    if (Get-Service $svc -ErrorAction SilentlyContinue) { Stop-Service $svc -Force -ErrorAction SilentlyContinue; Write-Log "Servicio $svc detenido" }
}
# Lo que quede vivo dentro de la carpeta (postgres.exe, python.exe) se cierra para que suelte los archivos
foreach ($i in 1..15) {
    $p = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) }
    if (-not $p) { break }
    $p | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2
}
$targets = @($PgData, $FilesDir, $UpdateDir, $BackupDir, (Join-Path $Root 'app.prev'), (Join-Path $Root 'app.new'), (Join-Path $Root 'LEEME-GOLDEN-LOCAL.txt'))
foreach ($t in $targets) {
    if (Test-Path $t) { Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue; Write-Log "Eliminado: $t" }
}
# Secretos y vinculación: el archivo entero (SECRET_KEY, LOCAL_DB_PASSWORD, DATABASE_URL, NODE_TOKEN, SERVER_KEY, INSTALLATION_ID). Una instalación nueva genera secretos nuevos y pide otra llave.
if (Test-Path $EnvFile) { Remove-Item $EnvFile -Force -ErrorAction SilentlyContinue; Write-Log 'Eliminado: config\local.env (secretos y vinculación)' }
Get-ChildItem $ConfigDir -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
# Llaves de los certificados (la autoridad y el servidor) y la autoridad instalada en Windows
if (Test-Path $CertDir) { Remove-Item $CertDir -Recurse -Force -ErrorAction SilentlyContinue; Write-Log 'Eliminado: certs\ (llaves de la autoridad y del servidor)' }
try {
    Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue | Where-Object { $_.Subject -like '*Golden Local CA*' } | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Log 'Autoridad «Golden Local CA» retirada de Windows'
} catch { Write-Log "No se pudo retirar la autoridad de Windows: $_" }
# Registros al final (contienen rutas y horas, no datos personales; se borran igual)
if (Test-Path $LogDir) { Get-ChildItem $LogDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'instalador.log' } | Remove-Item -Force -ErrorAction SilentlyContinue }
if ($Overwrite) {
    Write-Host 'Sobrescribiendo el espacio libre del disco para que lo borrado no se pueda recuperar (puede tardar mucho)...'
    & cipher.exe /w:$Root | Out-Null
    Write-Log 'Espacio libre sobrescrito (cipher /w)'
}
Write-Log '== Datos borrados. Para dejar el equipo limpio del todo: Panel de control > Programas > desinstalar «Golden Local» y borrar C:\GoldenLocal =='
Write-Host 'Listo. Datos, copias, secretos y vinculación eliminados. Ahora desinstala «Golden Local» desde Programas y borra la carpeta C:\GoldenLocal.' -ForegroundColor Green
