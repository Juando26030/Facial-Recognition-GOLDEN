# Rutas y utilidades comunes del servidor local de Windows (Fase 6). Lo cargan los demás scripts con:  . "$PSScriptRoot\config.ps1"
# Diseño: TODO vive en C:\GoldenLocal (sin Docker). Subcarpetas:
#   app\        la aplicación (se reemplaza entera al actualizar)         python\   Python embebido
#   pgsql\      PostgreSQL (binarios)                                      tools\    WinSW (servicios)
#   scripts\    estos scripts                                              config\   local.env (secretos; solo SYSTEM y Administradores)
#   data\       pgdata (la base), files (fotos y documentos), update (peticiones de actualización)
#   backups\    copias de la base (antes de cada actualización y diarias)  logs\     registros   certs\ certificados
$ErrorActionPreference = 'Stop'
$Root      = if ($env:GOLDEN_LOCAL_ROOT) { $env:GOLDEN_LOCAL_ROOT } else { 'C:\GoldenLocal' }
$AppDir    = Join-Path $Root 'app'
$PyDir     = Join-Path $Root 'python'
$PgDir     = Join-Path $Root 'pgsql'
$ToolsDir  = Join-Path $Root 'tools'
$ScriptsDir= Join-Path $Root 'scripts'
$ConfigDir = Join-Path $Root 'config'
$DataDir   = Join-Path $Root 'data'
$PgData    = Join-Path $DataDir 'pgdata'
$FilesDir  = Join-Path $DataDir 'files'
$UpdateDir = Join-Path $DataDir 'update'
$BackupDir = Join-Path $Root 'backups'
$LogDir    = Join-Path $Root 'logs'
$CertDir   = Join-Path $Root 'certs'
$EnvFile   = Join-Path $ConfigDir 'local.env'
$Python    = Join-Path $PyDir 'python.exe'
$PgPort    = 5433                      # distinto de 5432 para no chocar con un Postgres que el equipo ya tenga
$AppPort   = 8443
$SvcPg     = 'GoldenLocalDB'
$SvcApp    = 'GoldenLocalApp'
$SvcUpd    = 'GoldenLocalUpdater'

function Write-Log([string]$Msg, [string]$File = 'instalador.log') {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Msg
    Add-Content -Path (Join-Path $LogDir $File) -Value $line -Encoding UTF8
    Write-Host $line
}

function Read-EnvFile([string]$Path = $EnvFile) {
    $h = @{}
    if (Test-Path $Path) {
        Get-Content $Path -Encoding UTF8 | ForEach-Object {
            if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $h[$Matches[1]] = $Matches[2] }
        }
    }
    return $h
}

function Set-EnvKey([string]$Key, [string]$Value) {
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
    $lines = @(); if (Test-Path $EnvFile) { $lines = @(Get-Content $EnvFile -Encoding UTF8) }
    $found = $false
    # @(...) fuerza una lista: con una sola línea PowerShell devuelve un texto suelto y «+=» pegaba las variables en una sola línea
    $lines = @($lines | ForEach-Object { if ($PSItem -match "^\s*$Key\s*=") { $found = $true; "$Key=$Value" } else { $PSItem } })
    if (-not $found) { $lines = @($lines) + @("$Key=$Value") }
    Set-Content -Path $EnvFile -Value $lines -Encoding UTF8
}

function Protect-File([string]$Path) {
    # Solo SYSTEM y Administradores pueden leer los secretos.
    & icacls $Path /inheritance:r /grant:r '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
}

function New-RandomSecret([int]$Bytes = 32) {
    $b = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return ([BitConverter]::ToString($b) -replace '-', '').ToLower()
}

function Import-GoldenEnv {
    # Carga local.env en las variables de entorno del proceso actual (lo usan la app, las migraciones y el respaldo).
    (Read-EnvFile).GetEnumerator() | ForEach-Object { Set-Item -Path "Env:$($_.Key)" -Value $_.Value }
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # JSON/archivos que lee Python: UTF-8 SIN marca de orden de bytes (con ella json.loads falla).
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-UpdateStatus([string]$State, [string]$Message, [hashtable]$Extra = @{}) {
    New-Item -ItemType Directory -Force -Path $UpdateDir | Out-Null
    $o = @{ state = $State; message = $Message; at = (Get-Date).ToUniversalTime().ToString('s') } + $Extra
    Write-Utf8NoBom (Join-Path $UpdateDir 'update-status.json') ($o | ConvertTo-Json -Compress)
    Write-Log "[actualización] $State - $Message" 'actualizador.log'
}

function Get-LanAddresses {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
        ForEach-Object { $_.IPAddress }
}

function Update-ServerCert {
    # Si este equipo cambió de dirección IP (de fija a automática o al revés, otro router), el certificado HTTPS ya no cubre la nueva y el navegador de los otros equipos avisaría.
    # Se vuelve a firmar con la MISMA autoridad (los celulares que ya la instalaron no repiten nada) y conserva las direcciones anteriores. Devuelve $true si regeneró (hay que reiniciar la app para que lo lea).
    $serverPem = Join-Path $CertDir 'server.pem'
    if (-not (Test-Path $serverPem)) { return $false }
    $ips = @(Get-LanAddresses)
    if ($ips.Count -eq 0) { return $false }
    try {
        $missing = "$(& $Python (Join-Path $ScriptsDir 'gen_cert.py') --missing $serverPem @ips)".Trim()
        if (-not $missing) { return $false }
        Write-Log "Certificado HTTPS: falta cubrir la(s) dirección(es) $missing; se vuelve a firmar" 'actualizador.log'
        & $Python (Join-Path $ScriptsDir 'gen_cert.py') $CertDir $env:COMPUTERNAME @ips | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Log 'Certificado HTTPS: no se pudo volver a firmar' 'actualizador.log'; return $false }
        return $true
    } catch { Write-Log "Certificado HTTPS: $_" 'actualizador.log'; return $false }
}

function Invoke-Pg([string]$Tool, [string[]]$Arguments) {
    # Herramientas cliente de PostgreSQL (psql, pg_dump, pg_restore) con la clave del archivo de configuración.
    $e = Read-EnvFile
    $env:PGPASSWORD = $e['LOCAL_DB_PASSWORD']
    & (Join-Path $PgDir "bin\$Tool.exe") -h 127.0.0.1 -p $PgPort -U golden @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Tool terminó con error ($LASTEXITCODE)" }
}

function Backup-Database([string]$Prefix) {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $f = Join-Path $BackupDir ("{0}-{1:yyyyMMdd-HHmmss}.dump" -f $Prefix, (Get-Date))
    Invoke-Pg 'pg_dump' @('-Fc', '-f', $f, 'golden')
    if (-not (Test-Path $f) -or (Get-Item $f).Length -lt 1024) { throw 'La copia de la base salió vacía' }
    return $f
}
