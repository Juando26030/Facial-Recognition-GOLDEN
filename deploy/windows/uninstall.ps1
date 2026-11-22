# Desinstalación del servidor local (la corre el desinstalador). Por seguridad NO borra la base de datos ni los archivos del evento (C:\GoldenLocal\data) ni las copias (backups\):
# si se quiere borrar todo (devolver o prestar el portátil), ANTES de desinstalar se corre scripts\borrar-datos.ps1 (confirma que los eventos ya se subieron a la nube: «Pasar a internet» con 0 pendientes).
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
Write-Log '== Desinstalación =='
foreach ($svc in @($SvcUpd, $SvcApp)) {
    if (Get-Service $svc -ErrorAction SilentlyContinue) { Stop-Service $svc -Force -ErrorAction SilentlyContinue; & (Join-Path $ToolsDir "$svc.exe") uninstall }
}
if (Get-Service $SvcPg -ErrorAction SilentlyContinue) { Stop-Service $SvcPg -Force -ErrorAction SilentlyContinue; & (Join-Path $PgDir 'bin\pg_ctl.exe') unregister -N $SvcPg }
Get-NetFirewallRule -DisplayName 'Golden Local (HTTPS)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Log 'Servicios y regla de cortafuegos retirados. Los datos quedan en C:\GoldenLocal\data y las copias en C:\GoldenLocal\backups (para borrarlos de forma segura: scripts\borrar-datos.ps1).'
