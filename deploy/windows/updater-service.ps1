# Servicio GoldenLocalUpdater (corre como SYSTEM). Cada 5 segundos mira si la app dejó una petición de «Actualizar ahora» (data\update\update-request.json) y, si la hay, corre run-update.ps1.
# Además hace la copia diaria de la base a las 3:00 a. m. (se conservan las últimas 14) y renueva el certificado HTTPS si le quedan menos de 60 días (al reiniciar el servicio de la app).
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Continue'
Write-Log 'Actualizador iniciado' 'actualizador.log'
$lastBackupDay = ''
$lastCertCheck = [datetime]::MinValue
while ($true) {
    try {
        $req = Join-Path $UpdateDir 'update-request.json'
        if (Test-Path $req) { & (Join-Path $ScriptsDir 'run-update.ps1') }
        # Llave deshabilitada en la nube (la app escribe SERVER_DISABLED=1 solo cuando la nube lo confirmó): baja automática, una sola vez (docs/17_SERVIDOR_LOCAL.md § Llaves)
        $envNow = Read-EnvFile
        if (("$($envNow['SERVER_DISABLED'])" -match '^(1|true|yes|si)$') -and ("$($envNow['LOCAL_WIPE_ON_DISABLE'])" -ne '0') -and -not $envNow['SERVER_WIPE_STARTED']) {
            Set-EnvKey 'SERVER_WIPE_STARTED' (Get-Date).ToString('s')
            Write-Log 'Llave deshabilitada en la nube: se inicia la baja automática (borrado de datos y desinstalación)' 'actualizador.log'
            $act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $ScriptsDir 'autodestruir.ps1')`""
            Register-ScheduledTask -TaskName 'GoldenLocalBaja' -Action $act -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
            Start-ScheduledTask -TaskName 'GoldenLocalBaja'
        }
        $now = Get-Date
        if (($now - $lastCertCheck).TotalSeconds -ge 60) {          # cada minuto: ¿cambió la IP del equipo? (no toca la base; solo lee los adaptadores y el certificado)
            $lastCertCheck = $now
            Update-RouteMetrics | Out-Null          # el cable al router sin internet no debe quitarle la salida a la sincronización
            if (Update-ServerCert) {
                Restart-Service $SvcApp -Force -ErrorAction SilentlyContinue
                Write-Log 'Certificado HTTPS renovado por cambio de dirección IP; se reinició la aplicación' 'actualizador.log'
            }
        }
        if ($now.Hour -eq 3 -and $lastBackupDay -ne $now.ToString('yyyyMMdd')) {
            $lastBackupDay = $now.ToString('yyyyMMdd')
            try {
                $f = Backup-Database 'diaria'; Write-Log "Copia diaria: $f" 'actualizador.log'
                Get-ChildItem $BackupDir -Filter 'diaria-*.dump' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 | Remove-Item -Force
            } catch { Write-Log "Copia diaria falló: $_" 'actualizador.log' }
        }
    } catch { Write-Log "Error en el ciclo del actualizador: $_" 'actualizador.log' }
    Start-Sleep -Seconds 5
}
