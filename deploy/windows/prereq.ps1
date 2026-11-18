# Requisitos de Windows para el servidor local. Lo corre install.ps1 (siempre, con permisos de administrador) y también el acceso directo «Golden Local - verificar y reparar».
# No hace falta ninguna «función de Windows Server»: la app lleva su propio Python y su propia base PostgreSQL. Aquí se comprueba y se deja listo lo único que Windows debe tener:
#   1) Windows 10/11 (o Server 2016+) de 64 bits   2) componente «Visual C++ 2015-2022 x64» (lo necesita PostgreSQL; si falta se instala el que viene incluido, sin internet)
#   3) servicio de cortafuegos activo y red del equipo en modo que permita entrar desde la red local   4) puerto de la app libre   5) reloj en hora (los certificados dependen de él)
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
$notes = @()
function Note([string]$t) { $script:notes += $t; Write-Log $t }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" ; exit 0
}

# 1) Sistema operativo
$os = Get-CimInstance Win32_OperatingSystem
if (-not [Environment]::Is64BitOperatingSystem -or [int]($os.BuildNumber) -lt 14393) { throw 'Este equipo no sirve: se necesita Windows 10/11 (o Server 2016 en adelante) de 64 bits.' }
Note "Windows: $($os.Caption) (compilación $($os.BuildNumber))"

# 2) Visual C++ 2015-2022 x64
function Test-Vc { $k = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'; (Test-Path $k) -and ((Get-ItemProperty $k).Installed -eq 1) }
if (Test-Vc) { Note 'Visual C++ x64: ya está instalado' }
else {
    $vc = Join-Path $ToolsDir 'vc_redist.x64.exe'
    if (-not (Test-Path $vc)) { throw 'Falta el componente Visual C++ dentro del instalador (tools\vc_redist.x64.exe). Vuelve a descargar el instalador.' }
    $p = Start-Process $vc -ArgumentList '/install /quiet /norestart' -Wait -PassThru
    if ($p.ExitCode -in 0, 1638, 3010) { Note "Visual C++ x64: instalado (código $($p.ExitCode))" } else { throw "No se pudo instalar Visual C++ (código $($p.ExitCode))" }
}

# 3) Cortafuegos y tipo de red: una red marcada «Pública» bloquea la entrada; la regla propia de la app (install.ps1) ya limita a la red local, así que se pasa a «Privada» solo las conexiones activas con red local
$svc = Get-Service MpsSvc -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne 'Running') { Set-Service MpsSvc -StartupType Automatic; Start-Service MpsSvc; Note 'Servicio de cortafuegos de Windows: encendido' }
foreach ($c in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' -and $_.IPv4Connectivity -ne 'Disconnected' })) {
    try { Set-NetConnectionProfile -InterfaceIndex $c.InterfaceIndex -NetworkCategory Private; Note "Red «$($c.Name)»: pasada a Privada para que los demás equipos puedan entrar" } catch { Note "No se pudo cambiar la red «$($c.Name)»: $_" }
}

# 4) Puerto libre (solo si la app aún no está instalada/corriendo)
$appSvc = Get-Service $SvcApp -ErrorAction SilentlyContinue
if (-not $appSvc -or $appSvc.Status -ne 'Running') {
    $busy = Get-NetTCPConnection -LocalPort $AppPort -State Listen -ErrorAction SilentlyContinue
    if ($busy) { throw "El puerto $AppPort ya lo usa otro programa. Ciérralo y vuelve a intentar." }
}

# 5) Reloj
try { Start-Service W32Time -ErrorAction SilentlyContinue; & w32tm /resync /nowait 2>$null | Out-Null } catch {}

Note 'Requisitos listos.'
if ($Host.Name -eq 'ConsoleHost' -and $MyInvocation.InvocationName -ne '.' -and -not $env:GOLDEN_SILENT) { Write-Host ($notes -join "`n"); Read-Host 'Pulsa Enter para cerrar' | Out-Null }
