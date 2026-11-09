# Desinstalación del servidor local (la corre el desinstalador). Por seguridad NO borra la base de datos ni los archivos del evento (C:\GoldenLocal\data) ni las copias (backups\):
# si se quiere borrar todo, se borra esa carpeta a mano DESPUÉS de confirmar que los eventos ya se subieron a la nube.
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
Write-Log '== Desinstalación =='
foreach ($svc in @($SvcUpd, $SvcApp)) {
    if (Get-Service $svc -ErrorAction SilentlyContinue) { Stop-Service $svc -Force -ErrorAction SilentlyContinue; & (Join-Path $ToolsDir "$svc.exe") uninstall }
}
if (Get-Service $SvcPg -ErrorAction SilentlyContinue) { Stop-Service $SvcPg -Force -ErrorAction SilentlyContinue; & (Join-Path $PgDir 'bin\pg_ctl.exe') unregister -N $SvcPg }
Get-NetFirewallRule -DisplayName 'Golden Local (HTTPS)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Log 'Servicios y regla de cortafuegos retirados. Los datos quedan en C:\GoldenLocal\data y las copias en C:\GoldenLocal\backups.'
