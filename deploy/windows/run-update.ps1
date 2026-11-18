# Actualización del servidor local a la versión de producción (Fase 6). La dispara la petición que escribe la app (app/local_update.py); corre como SYSTEM dentro del servicio GoldenLocalUpdater.
# Pasos, cada uno anunciado en data\update\update-status.json (la pantalla lo muestra): 1 copia de la base -> 2 descarga y verificación SHA-256 -> 3 cambio de archivos -> 4 migraciones -> 5 reinicio y comprobación.
# Si CUALQUIER paso falla después de tocar algo: se vuelve a la versión anterior de los archivos Y a la copia de la base, y el estado queda «rolledback». Si falla antes de tocar algo (copia, descarga, huella): «error» y nada cambia.
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Stop'
$reqPath = Join-Path $UpdateDir 'update-request.json'
$pkg = Join-Path $UpdateDir 'package.zip'
$new = Join-Path $Root 'app.new'
$old = Join-Path $Root 'app.prev'
$touched = $false
$backup = $null

function Remove-Quietly($p) { if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue } }

function Restore-Previous {
    Write-Log 'Volviendo a la versión anterior' 'actualizador.log'
    Stop-Service $SvcApp -Force -ErrorAction SilentlyContinue
    if (Test-Path $old) { Remove-Quietly $AppDir; Move-Item $old $AppDir }
    if ($backup -and (Test-Path $backup)) {
        try {
            Invoke-Pg 'dropdb' @('--if-exists', '--force', 'golden')
            Invoke-Pg 'createdb' @('golden')
            Invoke-Pg 'pg_restore' @('--no-owner', '-d', 'golden', $backup)
        } catch { Write-Log "No se pudo restaurar la base desde la copia ($backup): $_" 'actualizador.log' }
    }
    Start-Service $SvcApp -ErrorAction SilentlyContinue
}

try {
    $req = Get-Content $reqPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not "$($req.package_url)".StartsWith('https://')) { throw 'La dirección del paquete no es HTTPS' }
    if ("$($req.sha256)" -notmatch '^[0-9a-f]{64}$') { throw 'La huella del paquete no es válida' }
    Import-GoldenEnv
    # F5-9 A-04: la petición la escribe la app (o quien pueda escribir en data\update): NO se confía en su dirección ni en su huella. Se vuelve a preguntar a producción
    # (HTTPS, sin redirecciones) y solo se sigue si coincide EXACTAMENTE con lo publicado; se instala lo que dice producción, no lo que dice el archivo.
    $prod = "$env:PRODUCTION_URL".Trim().TrimEnd('/')
    if (-not $prod.StartsWith('https://')) { throw 'PRODUCTION_URL no es HTTPS' }
    $manifest = Invoke-RestMethod -Uri "$prod/api/ops/update-manifest" -UseBasicParsing -TimeoutSec 30 -MaximumRedirection 0
    if (-not $manifest.available -or "$($manifest.package_url)" -ne "$($req.package_url)" -or "$($manifest.sha256)".ToLower() -ne "$($req.sha256)") {
        throw 'La petición no coincide con el paquete que publica producción'
    }
    $pkgUrl = "$($manifest.package_url)"; $pkgSha = "$($manifest.sha256)".ToLower()
    if (-not $pkgUrl.StartsWith('https://') -or $pkgSha -notmatch '^[0-9a-f]{64}$') { throw 'Producción no publica un paquete válido' }

    Write-UpdateStatus 'backup' 'Guardando una copia de la base de datos'
    $backup = Backup-Database 'antes-de-actualizar'

    Write-UpdateStatus 'download' 'Descargando la versión nueva'
    Remove-Quietly $pkg
    Invoke-WebRequest -Uri $pkgUrl -OutFile $pkg -UseBasicParsing -TimeoutSec 1800
    $hash = (Get-FileHash $pkg -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $pkgSha) { Remove-Quietly $pkg; throw 'La descarga no coincide con la huella de producción; no se instaló nada' }

    Write-UpdateStatus 'apply' 'Instalando la versión nueva'
    Remove-Quietly $new; Remove-Quietly $old
    Expand-Archive -Path $pkg -DestinationPath $new -Force
    if (-not (Test-Path (Join-Path $new 'alembic.ini')) -or -not (Test-Path (Join-Path $new 'app\main.py'))) { throw 'El paquete no trae la aplicación completa' }

    # ---- desde aquí se toca el sistema: cualquier falla vuelve atrás
    $touched = $true
    Stop-Service $SvcApp -Force
    Move-Item $AppDir $old
    Move-Item $new $AppDir
    $oldReq = Join-Path $old 'requirements-local.txt'; $newReq = Join-Path $AppDir 'requirements-local.txt'
    if ((Test-Path $newReq) -and (-not (Test-Path $oldReq) -or (Get-FileHash $oldReq).Hash -ne (Get-FileHash $newReq).Hash)) {
        Write-UpdateStatus 'apply' 'Instalando las piezas nuevas de la aplicación'
        & $Python -m pip install -r $newReq --no-warn-script-location --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las piezas nuevas' }
    }

    Write-UpdateStatus 'migrate' 'Actualizando la base de datos'
    Push-Location $AppDir
    try { & $Python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Las migraciones fallaron' } } finally { Pop-Location }

    Write-UpdateStatus 'restart' 'Reiniciando el servidor'
    Start-Service $SvcApp
    $healthy = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 3
        $code = & curl.exe -k -s -o NUL -w '%{http_code}' "https://localhost:$AppPort/health"
        if ($code -eq '200') { $healthy = $true; break }
    }
    if (-not $healthy) { throw 'El servidor no respondió después de actualizar' }

    Remove-Quietly $pkg
    Write-UpdateStatus 'ok' "Actualizado a la versión $($req.target_commit)" @{ backup = $backup; from = $req.from_commit; to = $req.target_commit }
}
catch {
    $why = "$_"
    if ($touched) { Restore-Previous; Write-UpdateStatus 'rolledback' "La actualización falló ($why). Se volvió a la versión anterior." @{ backup = $backup } }
    else { Write-UpdateStatus 'error' "La actualización no se pudo hacer ($why). No se cambió nada." @{ backup = $backup } }
}
finally {
    Remove-Quietly $reqPath
}
