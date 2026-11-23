# Baja automática del servidor local (22-nov-2026, decisión de Juan David): cuando un administrador DESHABILITA la llave de producto en la nube y este servidor se entera (la nube respondió «servidor
# deshabilitado»), el servicio actualizador lanza este script UNA vez. Hace lo mismo que hacer a mano «borrar-datos.ps1 -Yes» + desinstalar + borrar la carpeta: elimina la base, los archivos de los eventos,
# las copias, los registros, los secretos, las llaves y la autoridad de certificados; corre el desinstalador (servicios y regla del cortafuegos) y borra C:\GoldenLocal. Lo que no se haya subido a la nube
# se pierde: por eso deshabilitar pide escribir una palabra y avisa antes. Apagable con LOCAL_WIPE_ON_DISABLE=0 en config\local.env. Corre como SYSTEM en una tarea programada aparte (el servicio
# actualizador se detiene durante el borrado, y un proceso hijo suyo moriría con él). Deja SOLO una línea con la fecha en C:\ProgramData\GoldenLocal-baja.log (sin datos personales).
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
$ledger = 'C:\ProgramData\GoldenLocal-baja.log'
# Candado (revisión 23-nov, L2): solo corre si la nube confirmó la baja (SERVER_DISABLED) y no está apagada (LOCAL_WIPE_ON_DISABLE=0). Ejecutado a mano o por error, NO borra nada.
$envChk = Read-EnvFile
if (-not ("$($envChk['SERVER_DISABLED'])" -match '^(1|true|yes|si)$') -or "$($envChk['LOCAL_WIPE_ON_DISABLE'])" -eq '0') {
    Write-Log 'Baja automática NO ejecutada: la llave no está deshabilitada en la nube (o la baja está apagada).'
    exit 0
}
Write-Log '== Baja automática: la llave fue deshabilitada en la nube =='
try {
    & (Join-Path $ScriptsDir 'borrar-datos.ps1') -Yes
} catch { Write-Log "borrar-datos falló: $_" }
$un = Join-Path $Root 'unins000.exe'
if (Test-Path $un) {
    Start-Process -FilePath $un -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -ErrorAction SilentlyContinue
} else {
    & (Join-Path $ScriptsDir 'uninstall.ps1')
}
try { Add-Content -Path $ledger -Value ("{0:yyyy-MM-dd HH:mm:ss}  Servidor local dado de baja automáticamente (llave deshabilitada en la nube)." -f (Get-Date)) -Encoding UTF8 } catch { }
Unregister-ScheduledTask -TaskName 'GoldenLocalBaja' -Confirm:$false -ErrorAction SilentlyContinue
# La carpeta entera se borra al final, desde fuera de ella (este script vive dentro)
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "ping 127.0.0.1 -n 8 >nul & rmdir /s /q `"$Root`"" -WindowStyle Hidden
