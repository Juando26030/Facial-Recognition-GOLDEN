# Baja la aplicación con la llave de producto (20-nov-2026). El instalador liviano NO lleva el código de la app: lo entrega producción solo a quien tenga una llave válida.
# Lo corre install.ps1 cuando el asistente dejó config\install-request.json ({key, installation_id}). Pasos: 1) reclama la llave (POST /api/node/key/claim: queda atada a ESTA instalación y recibe un permiso
# temporal), 2) descarga el paquete con ese permiso y verifica su huella SHA-256, 3) lo despliega en app\ e instala las piezas de Python que falten. Si algo falla: error claro y no se toca la app anterior.
. "$PSScriptRoot\config.ps1"
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
$reqFile = Join-Path $ConfigDir 'install-request.json'
if (-not (Test-Path $reqFile)) { throw 'Falta la llave de producto (config\install-request.json). Vuelve a ejecutar el instalador y escríbela.' }
$req = Get-Content $reqFile -Raw -Encoding UTF8 | ConvertFrom-Json
$key = "$($req.key)".Trim().ToUpper(); $inst = "$($req.installation_id)".Trim()
if (-not $inst) {          # el asistente solo deja la llave: la identificación de ESTA instalación (la llave queda atada a ella) se genera aquí y se guarda para install.ps1
    $inst = [guid]::NewGuid().ToString('N')
    Write-Utf8NoBom $reqFile (@{ key = $key; installation_id = $inst } | ConvertTo-Json -Compress)
}
if ($key -notmatch '^GLD-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$') { throw 'La llave de producto no tiene el formato correcto (GLD-XXXX-XXXX-XXXX).' }
if ($inst -notmatch '^[0-9a-f]{32}$') { throw 'La identificación de esta instalación no es válida; vuelve a ejecutar el instalador.' }

$defaults = Read-EnvFile (Join-Path $ScriptsDir 'defaults.env')
$prod = ("$($defaults['PRODUCTION_URL'])").Trim().TrimEnd('/')
$cur = Read-EnvFile
if ($cur['PRODUCTION_URL']) { $prod = "$($cur['PRODUCTION_URL'])".Trim().TrimEnd('/') }
if (-not $prod.StartsWith('https://')) { throw 'La dirección de producción no es HTTPS.' }

Write-Log 'Reclamando la llave de producto…'
try {
    $claim = Invoke-RestMethod -Uri "$prod/api/node/key/claim" -Method Post -ContentType 'application/json' -Body (@{ key = $key; installation_id = $inst } | ConvertTo-Json -Compress) -UseBasicParsing -TimeoutSec 60 -MaximumRedirection 0
} catch {
    $msg = ''
    try { $msg = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() | ConvertFrom-Json | Select-Object -ExpandProperty detail } catch { }
    if ($msg) { throw "Producción no aceptó la llave: $msg" }
    throw 'No se pudo hablar con producción. Revisa que este equipo tenga internet para instalar (solo se necesita al instalar y al vincular).'
}
$pkgUrl = "$($claim.package_url)"; $sha = "$($claim.sha256)".ToLower()
if (-not $pkgUrl.StartsWith('https://') -or $sha -notmatch '^[0-9a-f]{64}$') { throw 'Producción no publica un paquete válido todavía. Avisa al equipo de Golden.' }

$pkg = Join-Path $UpdateDir 'install-package.zip'
New-Item -ItemType Directory -Force -Path $UpdateDir | Out-Null
Remove-Item $pkg -Force -ErrorAction SilentlyContinue
Write-Log 'Descargando la aplicación…'
$headers = @{}
if ($pkgUrl.StartsWith($prod + '/')) { $headers = @{ 'X-Install-Ticket' = "$($claim.ticket)"; 'X-Install-Id' = $inst } }          # el permiso solo viaja a producción, nunca a otro servidor
Invoke-WebRequest -Uri $pkgUrl -OutFile $pkg -Headers $headers -UseBasicParsing -TimeoutSec 1800 -MaximumRedirection 0
if ((Get-FileHash $pkg -Algorithm SHA256).Hash.ToLower() -ne $sha) { Remove-Item $pkg -Force; throw 'La descarga no coincide con la huella de producción; no se instaló nada.' }

$new = Join-Path $Root 'app.new'; $old = Join-Path $Root 'app.prev'
Remove-Item $new, $old -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -Path $pkg -DestinationPath $new -Force
if (-not (Test-Path (Join-Path $new 'alembic.ini')) -or -not (Test-Path (Join-Path $new 'app\main.py'))) { Remove-Item $new -Recurse -Force; throw 'El paquete no trae la aplicación completa.' }
if (Test-Path $AppDir) { Move-Item $AppDir $old }
Move-Item $new $AppDir
Remove-Item $pkg -Force -ErrorAction SilentlyContinue
Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue

$reqTxt = Join-Path $AppDir 'requirements-local.txt'
if ((Test-Path $reqTxt) -and (Test-Path $Python)) {
    Write-Log 'Instalando las piezas de Python que falten…'
    & $Python -m pip install -r $reqTxt --no-warn-script-location --disable-pip-version-check --only-binary=:all:
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las piezas de Python de la aplicación.' }
}
Write-Log 'Aplicación descargada y verificada'
