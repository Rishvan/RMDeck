; Inno Setup script - build step 3 (run through build_installer.bat, which passes
; /DAppVersion=x.y.z). Produces dist\RMDex-Setup-x.y.z.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "RMDex"
#define AppExe "RMDex.exe"

[Setup]
AppId={{6F1E3C52-8A47-4C2B-9D1E-5B7A2C9E4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Rishvan
AppCopyright=Developed by Rishvan
VersionInfoCompany=Rishvan
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
; per-user install by default (no admin prompt); the user may choose "all users"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=RMDex-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; per-app audio capture needs Windows 10 version 2004 (build 19041) or newer
MinVersion=10.0.19041
; ask to close a running copy before installing / uninstalling
AppMutex=Local\RMDex.SingleInstance
CloseApplications=yes

[InstallDelete]
; same AppId as the app's earlier names (RMDeck, Capture Monitor), so this upgrades
; them; tidy up their old exe and shortcuts
Type: files; Name: "{app}\RMDeck.exe"
Type: files; Name: "{autoprograms}\RMDeck.lnk"
Type: files; Name: "{autodesktop}\RMDeck.lnk"
Type: files; Name: "{app}\CaptureMonitor.exe"
Type: files; Name: "{autoprograms}\Capture Monitor.lnk"
Type: files; Name: "{autodesktop}\Capture Monitor.lnk"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\build\dist\RMDex\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; AppUserModelID matches the app's, so the running window groups with a pinned shortcut
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Comment: "Mix app audio and your mic and listen live"; AppUserModelID: "RMDex.App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Comment: "Mix app audio and your mic and listen live"; AppUserModelID: "RMDex.App"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
