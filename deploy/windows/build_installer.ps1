# Construye el instalador de Windows del servidor local y el paquete de actualización (Fase 6). SE CORRE EN UNA MÁQUINA WINDOWS con internet (la de Juan David o el runner de GitHub Actions: .github/workflows/instalador-windows.yml).
# Requisitos en esa máquina: PowerShell 5.1+, Python 3.13 (para pip), Inno Setup 6 (iscc.exe en el PATH o en "C:\Program Files (x86)\Inno Setup 6"). Todo lo demás lo descarga el script.
#
# Salida (carpeta build\windows\out\):
#   GoldenLocal-Setup-<versión>.exe          el instalador de doble clic para los portátiles
#   golden-local-update-<versión>.zip        el paquete que descarga «Actualizar ahora»
#   golden-local-update-<versión>.sha256     su huella: se pone en UPDATE_PACKAGE_SHA256 de producción junto con UPDATE_PACKAGE_URL (donde se suba el .zip, HTTPS)
#
# Las versiones de lo que se descarga están fijadas aquí abajo (reproducible); para subirlas se cambian a propósito. Si se conoce la huella SHA-256 de una descarga se pone en el parámetro y se verifica.
param(
    [string]$Version = '',
    [string]$PythonEmbedVersion = '3.13.1',
    [string]$PostgresVersion = '18.0-1',
    [string]$WinSWVersion = 'v2.12.0',
    [string]$PythonEmbedSha256 = '', [string]$PostgresSha256 = '', [string]$WinSWSha256 = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Build = Join-Path $Repo 'build\windows'
$Payload = Join-Path $Build 'payload'
$Cache = Join-Path $Build 'cache'
$Out = Join-Path $Build 'out'

if (-not $Version) {
    $sha = (& git -C $Repo rev-parse --short=12 HEAD).Trim()
    $Version = (Get-Date -Format 'yyyy.MM.dd') + '-' + $sha
}
$commit = (& git -C $Repo rev-parse --short=12 HEAD).Trim()
Write-Host "== Construyendo Golden Local $Version (commit $commit) =="

function Get-Verified([string]$Url, [string]$File, [string]$Sha) {
    if (-not (Test-Path $File)) { Write-Host "Descargando $Url"; Invoke-WebRequest -Uri $Url -OutFile $File -UseBasicParsing }
    if ($Sha) { $h = (Get-FileHash $File -Algorithm SHA256).Hash.ToLower(); if ($h -ne $Sha.ToLower()) { Remove-Item $File; throw "La huella de $File no coincide ($h)" } }
    else { Write-Host ("  huella de {0}: {1}  (anótala en los parámetros para verificarla la próxima vez)" -f (Split-Path $File -Leaf), (Get-FileHash $File -Algorithm SHA256).Hash.ToLower()) }
}

Remove-Item $Payload -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Payload, $Cache, $Out | Out-Null

# ---- 1. La aplicación (solo lo que corre: sin pruebas, documentos ni scripts de nube)
$appDst = Join-Path $Payload 'app'
New-Item -ItemType Directory -Force -Path $appDst | Out-Null
foreach ($item in @('app', 'alembic', 'static', 'templates', 'alembic.ini')) { Copy-Item (Join-Path $Repo $item) (Join-Path $appDst $item) -Recurse -Force }
Get-ChildItem $appDst -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
& python (Join-Path $PSScriptRoot 'make_requirements.py') (Join-Path $Repo 'requirements.txt') (Join-Path $appDst 'requirements-local.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar requirements-local.txt' }
$bi = @{ commit = $commit; date = (Get-Date).ToUniversalTime().ToString('s') + 'Z' } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText((Join-Path $appDst '.build_info'), $bi, (New-Object System.Text.UTF8Encoding($false)))

# ---- 2. Paquete de actualización = la carpeta app\ comprimida (lo que descarga «Actualizar ahora»)
$zip = Join-Path $Out "golden-local-update-$Version.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $appDst '*') -DestinationPath $zip -CompressionLevel Optimal
$zipSha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Set-Content -Path (Join-Path $Out "golden-local-update-$Version.sha256") -Value "$zipSha  golden-local-update-$Version.zip" -Encoding ASCII

# ---- 3. Python embebido + pip + dependencias
$pyZip = Join-Path $Cache "python-$PythonEmbedVersion-embed-amd64.zip"
Get-Verified "https://www.python.org/ftp/python/$PythonEmbedVersion/python-$PythonEmbedVersion-embed-amd64.zip" $pyZip $PythonEmbedSha256
$pyDst = Join-Path $Payload 'python'
Expand-Archive $pyZip -DestinationPath $pyDst -Force
$pth = Get-ChildItem $pyDst -Filter 'python*._pth' | Select-Object -First 1
$lines = Get-Content $pth.FullName | ForEach-Object { if ($_ -match '^#\s*import site') { 'import site' } else { $_ } }
$lines += 'Lib\site-packages'; $lines += '..\app'          # la app se encuentra sin variables de entorno
Set-Content $pth.FullName $lines -Encoding ASCII
$getPip = Join-Path $Cache 'get-pip.py'
Get-Verified 'https://bootstrap.pypa.io/get-pip.py' $getPip ''
& (Join-Path $pyDst 'python.exe') $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar pip' }
& (Join-Path $pyDst 'python.exe') -m pip install -r (Join-Path $appDst 'requirements-local.txt') --no-warn-script-location --disable-pip-version-check --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias (¿alguna no tiene versión para Windows? revisa requirements-local.txt)' }

# ---- 4. PostgreSQL (binarios de EDB, solo lo necesario)
$pgZip = Join-Path $Cache "postgresql-$PostgresVersion-windows-x64-binaries.zip"
Get-Verified "https://get.enterprisedb.com/postgresql/postgresql-$PostgresVersion-windows-x64-binaries.zip" $pgZip $PostgresSha256
$pgTmp = Join-Path $Cache 'pg-extract'
Remove-Item $pgTmp -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $pgZip -DestinationPath $pgTmp -Force
Move-Item (Join-Path $pgTmp 'pgsql') (Join-Path $Payload 'pgsql')
foreach ($junk in @('doc', 'pgAdmin 4', 'StackBuilder', 'symbols', 'include')) { Remove-Item (Join-Path $Payload "pgsql\$junk") -Recurse -Force -ErrorAction SilentlyContinue }

# ---- 5. WinSW (servicios de Windows)
$tools = Join-Path $Payload 'tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Get-Verified "https://github.com/winsw/winsw/releases/download/$WinSWVersion/WinSW-x64.exe" (Join-Path $Cache "WinSW-$WinSWVersion.exe") $WinSWSha256
Copy-Item (Join-Path $Cache "WinSW-$WinSWVersion.exe") (Join-Path $tools 'WinSW.exe')
# Componente Visual C++ 2015-2022 x64 (lo necesita PostgreSQL; prereq.ps1 lo instala sin internet si el equipo no lo tiene)
Get-Verified 'https://aka.ms/vs/17/release/vc_redist.x64.exe' (Join-Path $Cache 'vc_redist.x64.exe') ''
Copy-Item (Join-Path $Cache 'vc_redist.x64.exe') (Join-Path $tools 'vc_redist.x64.exe')

# ---- 6. Instalador (Inno Setup)
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' }
if (-not (Test-Path $iscc)) { throw 'Falta Inno Setup 6 (https://jrsoftware.org/isinfo.php).' }
$env:GOLDEN_LOCAL_VERSION = $Version
& $iscc (Join-Path $PSScriptRoot 'GoldenLocal.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup falló' }

Write-Host ''
Write-Host "Listo. En $Out :"
Get-ChildItem $Out | ForEach-Object { Write-Host ("  {0}  ({1:N0} MB)" -f $_.Name, ($_.Length / 1MB)) }
Write-Host "Huella del paquete de actualización: $zipSha"
