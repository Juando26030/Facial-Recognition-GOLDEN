; Instalador del servidor local (Fase 6): UN solo archivo, doble clic, sin comandos. Se compila con Inno Setup 6 (build_installer.ps1). Lleva Python, PostgreSQL y las herramientas, pero NO el código de la app:
; (20-nov-2026) pide una LLAVE DE PRODUCTO (GLD-XXXX-XXXX-XXXX, de un solo uso, la crea un administrador en Configuración > Servidor local) y con ella baja la app de producción (scripts\download-app.ps1).
; Instala en C:\GoldenLocal y corre scripts\install.ps1 (servicios, base, certificados, energía). Pide permisos de administrador una sola vez.
#define AppVersion GetEnv("GOLDEN_LOCAL_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0"
#endif

; Marca de hora (UTC, aaaammddhhmmss) de CUANDO se construyó este instalador; la fija build_en_cloudshell.sh. Sirve para avisar si se va a instalar encima de una versión MÁS NUEVA.
#define BuildStamp GetEnv("GOLDEN_BUILD_STAMP")

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

// Antes de instalar: si ya hay una instalación MÁS NUEVA que este instalador (p. ej. se actualizó sola desde producción), se avisa y se recomienda bajar el instalador más reciente.
function OnlyDigits(const T: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(T) do
    if (T[I] >= '0') and (T[I] <= '9') then Result := Result + T[I];
end;

function InitializeSetup(): Boolean;
var
  Path: String;
  S: AnsiString;
  P: Integer;
  Inst, Mine: String;
begin
  Result := True;
  Mine := '{#BuildStamp}';
  Path := 'C:\GoldenLocal\app\.build_info';
  if (Length(Mine) <> 14) or (not FileExists(Path)) then Exit;
  if not LoadStringFromFile(Path, S) then Exit;
  P := Pos('"date":"', String(S));
  if P = 0 then Exit;
  Inst := OnlyDigits(Copy(String(S), P + 8, 20));
  if (Length(Inst) = 14) and (Inst > Mine) then
  begin
    if WizardSilent then
    begin
      Result := False;                 { instalación silenciosa: no se pisa una versión más nueva }
      Exit;
    end;
    Result := MsgBox('Este equipo ya tiene instalada una versión MÁS RECIENTE de Golden Local (' + Copy(Inst, 1, 4) + '-' + Copy(Inst, 5, 2) + '-' + Copy(Inst, 7, 2) + ' ' + Copy(Inst, 9, 2) + ':' + Copy(Inst, 11, 2) + ' UTC) que este instalador (' + Copy(Mine, 1, 4) + '-' + Copy(Mine, 5, 2) + '-' + Copy(Mine, 7, 2) + ' ' + Copy(Mine, 9, 2) + ':' + Copy(Mine, 11, 2) + ' UTC).' + #13#10#13#10 +
      'Si continúa, se sobrescribirá con una versión más vieja (después tendrá que actualizar de nuevo).' + #13#10#13#10 +
      'Lo recomendable es CANCELAR y descargar el instalador más reciente (o dejar que Golden Local se actualice solo desde «Actualizar ahora»).' + #13#10#13#10 + '¿Instalar de todos modos?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

// ---------------------------------------------------------------------------------------------- llave de producto
var
  KeyPage: TInputQueryWizardPage;
  InstallId: String;

function NewInstallId(): String;
var
  G: String;
begin
  G := CreateGuid() + CreateGuid();                    // 2 GUID -> 64 caracteres hexadecimales con llaves y guiones
  StringChangeEx(G, '{', '', True); StringChangeEx(G, '}', '', True); StringChangeEx(G, '-', '', True);
  Result := Lowercase(Copy(G, 1, 32));
end;

function EnvFlagOn(const Name: String): Boolean;
var
  S: AnsiString;
begin
  Result := False;
  if LoadStringFromFile('C:\GoldenLocal\config\local.env', S) then Result := (Pos(#10 + Name + '=1', #10 + String(S)) > 0);
end;

function AlreadyHasKey(): Boolean;
var
  S: AnsiString;
begin
  Result := False;
  if (not FileExists('C:\GoldenLocal\app\app\main.py')) then Exit;
  if LoadStringFromFile('C:\GoldenLocal\config\local.env', S) then
    Result := (Pos(#10 + 'SERVER_KEY=GLD-', #10 + String(S)) > 0) and (not EnvFlagOn('SERVER_DISABLED'));
end;

function ValidKey(K: String): Boolean;
var
  I: Integer;
  C: String;
begin
  Result := False;
  K := Uppercase(Trim(K));
  if (Length(K) <> 18) or (Copy(K, 1, 4) <> 'GLD-') or (K[9] <> '-') or (K[14] <> '-') then Exit;
  for I := 5 to 18 do
  begin
    if (I = 9) or (I = 14) then Continue;
    C := Copy(K, I, 1);
    if Pos(C, 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789') = 0 then Exit;
  end;
  Result := True;
end;

procedure InitializeWizard();
begin
  KeyPage := CreateInputQueryPage(wpWelcome, 'Llave de producto', 'Escribe la llave de este servidor', 'Te la da un administrador de Golden (Configuración › Servidor local). Es de un solo uso y se ata a este computador. Necesitas internet solo ahora, para bajar la aplicación.');
  KeyPage.Add('Llave (GLD-XXXX-XXXX-XXXX):', False);
  KeyPage.Edits[0].Text := ExpandConstant('{param:KEY|}');
  KeyPage.Edits[0].CharCase := ecUpperCase;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (KeyPage <> nil) and (PageID = KeyPage.ID) and AlreadyHasKey() and (ExpandConstant('{param:KEY|}') = '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (KeyPage <> nil) and (CurPageID = KeyPage.ID) then
  begin
    if not ValidKey(KeyPage.Edits[0].Text) then
    begin
      MsgBox('La llave no tiene el formato correcto. Se ve así: GLD-XXXX-XXXX-XXXX (sin letras O, I ni números 0, 1).', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir, Body: String;
begin
  if (CurStep = ssInstall) and (KeyPage <> nil) and (not ShouldSkipPage(KeyPage.ID)) then
  begin
    Dir := ExpandConstant('{app}\config');
    ForceDirectories(Dir);
    InstallId := NewInstallId();
    Body := '{"key":"' + Uppercase(Trim(KeyPage.Edits[0].Text)) + '","installation_id":"' + InstallId + '"}';
    SaveStringToFile(Dir + '\install-request.json', Body, False);
  end;
  if (CurStep = ssDone) and (not WizardSilent) and (not FileExists(ExpandConstant('{app}\app\app\main.py'))) then
    MsgBox('La instalación no se completó: la aplicación no se pudo descargar (llave no válida, ya usada o vencida, o sin internet). El detalle quedó en C:\GoldenLocal\logs\instalador.log. Pide una llave nueva a un administrador y vuelve a ejecutar el instalador.', mbError, MB_OK);
end;
