# Arranque de la aplicación (lo lanza el servicio GoldenLocalApp). Carga la configuración y corre la app en HTTPS. Sin reconocimiento facial (servicio «web»).
. "$PSScriptRoot\config.ps1"
Import-GoldenEnv
$env:LOCAL_ENV_FILE = $EnvFile
Set-Location $AppDir
Update-ServerCert | Out-Null          # si el equipo cambió de IP desde el último arranque, el certificado se vuelve a firmar ANTES de que la app lo lea
& $Python -m uvicorn app.entrypoints.web:app --host 0.0.0.0 --port $AppPort --workers 2 --ssl-keyfile (Join-Path $CertDir 'server.key') --ssl-certfile (Join-Path $CertDir 'server.pem') --no-server-header
exit $LASTEXITCODE
