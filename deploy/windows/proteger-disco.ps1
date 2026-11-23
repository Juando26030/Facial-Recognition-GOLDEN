# Cifrado del disco del servidor local con BitLocker (revisión de seguridad 22-nov-2026; docs/17_SERVIDOR_LOCAL.md § Seguridad del portátil). Es GRATIS: viene con Windows 10/11 Pro, Enterprise y Education
# (y en Home algunos equipos traen «Cifrado de dispositivo», también gratis). Este script NO compra ni instala nada: si el Windows de este equipo no lo trae, lo dice y no hace nada.
# Por qué: si roban el portátil, la base de datos y los rostros cifrados quedan en un disco legible. Con el disco cifrado, quien se lo lleve no puede leer nada sin la clave.
# La CLAVE DE RECUPERACIÓN nunca se escribe en el repositorio, en los registros ni en este chat: se guarda en una carpeta que TÚ indicas, que debe estar en OTRO medio (memoria USB o carpeta de
# red de la oficina) y se muestra una sola vez en pantalla. Sin esa clave, si el equipo falla, el disco no se puede abrir.
# Uso (PowerShell como administrador):  powershell -NoProfile -ExecutionPolicy Bypass -File C:\GoldenLocal\scripts\proteger-disco.ps1 -RecoveryKeyFolder E:\
param([string]$RecoveryKeyFolder = '', [switch]$StatusOnly)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Abre PowerShell como administrador y vuelve a correr este script.' -ForegroundColor Yellow; exit 1
}
$mount = $env:SystemDrive
$edition = (Get-CimInstance Win32_OperatingSystem).Caption
Write-Host "Windows: $edition"
if (-not (Get-Command Get-BitLockerVolume -ErrorAction SilentlyContinue)) {
    Write-Host 'Este Windows no trae BitLocker (suele pasar en la edición «Home»). Opciones gratuitas: Configuración > Privacidad y seguridad > «Cifrado de dispositivo» (si aparece, actívalo).' -ForegroundColor Yellow
    Write-Host 'Si no aparece, cifrar este disco exige Windows Pro (de pago): NO se hace nada y el portátil queda con el riesgo descrito en docs/17. Avisa a Juan David.' -ForegroundColor Yellow
    exit 2
}
$vol = Get-BitLockerVolume -MountPoint $mount
Write-Host "Disco $mount : protección $($vol.ProtectionStatus), cifrado al $($vol.EncryptionPercentage) %."
if ($StatusOnly) { exit 0 }
if ($vol.VolumeStatus -in 'FullyEncrypted', 'EncryptionInProgress' -and $vol.ProtectionStatus -eq 'On') { Write-Host 'Este disco ya está cifrado. No hay nada que hacer.' -ForegroundColor Green; exit 0 }
$tpm = Get-Tpm -ErrorAction SilentlyContinue
if (-not $tpm -or -not $tpm.TpmPresent -or -not $tpm.TpmReady) {
    Write-Host 'Este equipo no tiene un TPM listo, que es lo que permite cifrar sin pedir una clave en cada arranque. Sin TPM habría que escribir una contraseña cada vez que el portátil arranque (un corte de luz dejaría el evento detenido): NO se activa.' -ForegroundColor Yellow
    exit 3
}
if (-not $RecoveryKeyFolder -or -not (Test-Path $RecoveryKeyFolder)) { Write-Host 'Indica con -RecoveryKeyFolder una carpeta que exista (memoria USB o carpeta de red), para guardar la clave de recuperación.' -ForegroundColor Yellow; exit 4 }
if ((Resolve-Path $RecoveryKeyFolder).Path.StartsWith($mount, [StringComparison]::OrdinalIgnoreCase)) { Write-Host "La clave de recuperación NO puede guardarse en $mount (el mismo disco que se cifra). Usa otra unidad." -ForegroundColor Yellow; exit 5 }
Enable-BitLocker -MountPoint $mount -EncryptionMethod XtsAes256 -UsedSpaceOnly -TpmProtector | Out-Null
$prot = Add-BitLockerKeyProtector -MountPoint $mount -RecoveryPasswordProtector
$key = ($prot.KeyProtector | Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' } | Select-Object -Last 1).RecoveryPassword
$file = Join-Path $RecoveryKeyFolder ("BitLocker-clave-recuperacion-$($env:COMPUTERNAME).txt")
Set-Content -Path $file -Value @("Equipo: $($env:COMPUTERNAME)", "Fecha: $(Get-Date -Format 'yyyy-MM-dd')", "Clave de recuperación de BitLocker (disco $mount):", $key) -Encoding UTF8
Write-Host ''
Write-Host "Cifrado iniciado (sigue en segundo plano; el equipo se puede usar). Clave de recuperación guardada en: $file" -ForegroundColor Green
Write-Host "Clave (escríbela o fotografíala AHORA; no se vuelve a mostrar y no queda en ningún registro): $key" -ForegroundColor Cyan
Write-Host 'Guarda ese archivo FUERA del portátil (otra persona de confianza o caja fuerte). Quien tenga la clave puede abrir el disco.'
