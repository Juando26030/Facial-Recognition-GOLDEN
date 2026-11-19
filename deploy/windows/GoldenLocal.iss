; Instalador del servidor local (Fase 6): UN solo archivo, doble clic, sin comandos. Se compila con Inno Setup 6 (build_installer.ps1). Lleva TODO: la app, Python, PostgreSQL y las herramientas.
; Instala en C:\GoldenLocal y corre scripts\install.ps1 (servicios, base, certificados, energía). Pide permisos de administrador una sola vez.
#define AppVersion GetEnv("GOLDEN_LOCAL_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B7C0E-2E43-4D8A-9B53-7A4C1D6E0F11}
AppName=Golden Local
AppVersion={#AppVersion}
AppPublisher=Golden Eventos y Logística S.A.S.
DefaultDirName=C:\GoldenLocal
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\windows\out
OutputBaseFilename=GoldenLocal-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Golden Local (servidor sin internet)
; Si ya está instalado, se instala encima (actualización de emergencia): la base y la configuración NO se tocan.
CloseApplications=no
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\backups"; Flags: uninsneveruninstall
Name: "{app}\config"; Flags: uninsneveruninstall

[Files]
Source: "..\..\build\windows\payload\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\build\windows\payload\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\build\windows\payload\pgsql\*"; DestDir: "{app}\pgsql"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\build\windows\payload\tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "*.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "*.xml"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "gen_cert.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "defaults.env"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{commondesktop}\Golden Local"; Filename: "https://localhost:8443"; Comment: "Abrir el servidor local"
Name: "{commondesktop}\Golden Local - certificado para celulares"; Filename: "{app}\certs"
Name: "{commondesktop}\Golden Local - verificar y reparar"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\prereq.ps1"""; Comment: "Comprueba Windows, la red y el cortafuegos (pide permisos de administrador)"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\install.ps1"""; StatusMsg: "Instalando la base de datos, los servicios y los certificados (puede tardar unos minutos)..."; Flags: runhidden waituntilterminated
Filename: "https://localhost:8443"; Description: "Abrir Golden Local ahora"; Flags: postinstall shellexec skipifsilent nowait

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "GoldenLocalUninstall"

[Code]
// Si ya hay una instalación corriendo, se detienen sus servicios Y cualquier proceso que siga usando archivos de C:\GoldenLocal antes de copiar
// (la base y la configuración no se tocan). Sin esto, reinstalar encima fallaba con «código 5 / Acceso denegado» en pgsql\bin\icudt77.dll.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Ps: String;
begin
  Exec('net.exe', 'stop GoldenLocalUpdater', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec('net.exe', 'stop GoldenLocalApp', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec('net.exe', 'stop GoldenLocalDB', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { Lo que quede vivo (postgres.exe, python.exe, WinSW) se cierra: solo procesos cuyo ejecutable está dentro de la carpeta de instalación; se espera hasta 30 s a que suelten los archivos }
  Ps := '-NoProfile -ExecutionPolicy Bypass -Command "$d=''' + ExpandConstant('{app}') + '''; ' +
        'for($i=0;$i -lt 15;$i++){ $p=Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($d,[StringComparison]::OrdinalIgnoreCase) }; ' +
        'if(-not $p){break}; $p | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }"';
  Exec('powershell.exe', Ps, '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
