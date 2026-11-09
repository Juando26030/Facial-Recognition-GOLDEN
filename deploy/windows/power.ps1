# El servidor local NO se apaga ni se duerme solo (decisión de Juan David, 9-nov-2026): un turno puede durar 12 horas o más. Solo se apaga a mano.
# Se corre una vez al instalar (con permisos de administrador). Corriente (AC): nunca suspender, nunca hibernar, nunca apagar pantalla ni disco.
. "$PSScriptRoot\config.ps1"
Write-Log 'Ajustando energía: el equipo no se duerme ni se apaga solo (con corriente)'
& powercfg /change standby-timeout-ac 0
& powercfg /change hibernate-timeout-ac 0
& powercfg /change disk-timeout-ac 0
& powercfg /change monitor-timeout-ac 0
& powercfg /hibernate off
# Tapa del portátil: no hacer nada al cerrarla con corriente (para que un turno no muera al cerrar la tapa).
& powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
& powercfg /setactive SCHEME_CURRENT
# Windows Update no debe reiniciar solo mientras alguien tiene la sesión abierta, y las horas activas cubren el día completo.
$wu = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
New-Item -Path $wu -Force | Out-Null
Set-ItemProperty -Path $wu -Name 'NoAutoRebootWithLoggedOnUsers' -Type DWord -Value 1
Set-ItemProperty -Path $wu -Name 'AUOptions' -Type DWord -Value 3          # descarga y avisa; instalar lo decide una persona
$ux = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
if (Test-Path $ux) { Set-ItemProperty -Path $ux -Name 'ActiveHoursStart' -Type DWord -Value 0; Set-ItemProperty -Path $ux -Name 'ActiveHoursEnd' -Type DWord -Value 23 }
Write-Log 'Energía lista'
