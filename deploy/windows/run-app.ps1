# Arranque de la aplicación (lo lanza el servicio GoldenLocalApp). Carga la configuración y corre la app en HTTPS. Sin reconocimiento facial (servicio «web»).
. "$PSScriptRoot\config.ps1"
Import-GoldenEnv
Set-Location $AppDir
& $Python -m uvicorn app.entrypoints.web:app --host 0.0.0.0 --port $AppPort --workers 2 --ssl-keyfile (Join-Path $CertDir 'server.key') --ssl-certfile (Join-Path $CertDir 'server.pem') --no-server-header
exit $LASTEXITCODE
