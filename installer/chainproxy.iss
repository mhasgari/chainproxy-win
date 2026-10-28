; Inno Setup script for the Chain Proxy installer (built by dev/make_installer.py).
; Per-user install (no admin): the app writes runtime/, cache/ and core/ next to itself,
; which would not be writable under Program Files.
; Python and sing-box are NOT bundled: Run.bat downloads and verifies them on the first start
; (or uses the files in the offline folder).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "stage"
#endif

[Setup]
AppId={{6F1B9C52-5C0E-4E55-9E0A-C4A1F0B7D2E1}
AppName=Chain Proxy
AppVersion={#AppVersion}
AppPublisher=mhasgari
AppPublisherURL=https://github.com/mhasgari/chainproxy-win
AppSupportURL=https://github.com/mhasgari/chainproxy-win/issues
DefaultDirName={localappdata}\Programs\ChainProxy
DefaultGroupName=Chain Proxy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
#ifdef Full
OutputBaseFilename=ChainProxy-Setup-Full-{#AppVersion}
#else
OutputBaseFilename=ChainProxy-Setup-{#AppVersion}
#endif
SetupIconFile={#StageDir}\chainproxy.ico
UninstallDisplayIcon={app}\chainproxy.ico
LicenseFile={#StageDir}\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; your links and settings are never overwritten by an upgrade
Source: "{#StageDir}\subs.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#StageDir}\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#StageDir}\*"; DestDir: "{app}"; Excludes: "subs.txt,config.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Chain Proxy"; Filename: "{app}\Run.bat"; WorkingDir: "{app}"; IconFilename: "{app}\chainproxy.ico"
Name: "{autodesktop}\Chain Proxy"; Filename: "{app}\Run.bat"; WorkingDir: "{app}"; IconFilename: "{app}\chainproxy.ico"; Tasks: desktopicon
Name: "{autoprograms}\Chain Proxy Quick Start (PDF)"; Filename: "{app}\docs\Chain-Proxy-Quick-Start-fa.pdf"

[Run]
Filename: "{app}\Run.bat"; Description: "Start Chain Proxy now (the first start sets up Python and sing-box)"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent shellexec

[UninstallRun]
; give the Windows proxy settings back before the files go away
Filename: "{cmd}"; Parameters: "/c ""{app}\stop.bat"""; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "RestoreProxy"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\.proxy_state.json"
Type: files; Name: "{app}\.shortcuts_done"
Type: files; Name: "{app}\subs.txt"
Type: files; Name: "{app}\config.json"

[Code]
// an upgrade must not overwrite files that a running instance uses: switch it off first
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Rc: Integer;
begin
  if FileExists(ExpandConstant('{app}\stop.bat')) then
    Exec(ExpandConstant('{cmd}'), ExpandConstant('/c ""{app}\stop.bat""'), ExpandConstant('{app}'),
         SW_HIDE, ewWaitUntilTerminated, Rc);
  Result := '';
end;
