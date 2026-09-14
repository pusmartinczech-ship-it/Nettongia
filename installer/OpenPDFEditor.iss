#define MyAppName "Nettongia PDF Editor"
#define MyAppVersion GetEnv("OPENPDF_VERSION")
#define MyAppExeName "NettongiaPDFEditor.exe"

[Setup]
AppId={{3F9060A8-2B62-4F6D-BB67-D5C3D05D4057}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Nettongia contributors
DefaultDirName={autopf}\Nettongia PDF Editor
DefaultGroupName=Nettongia PDF Editor
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=Nettongia_PDF_Editor_{#MyAppVersion}-x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"

[Files]
Source: "..\dist\NettongiaPDFEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Nettongia PDF Editor"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Nettongia PDF Editor"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,Nettongia PDF Editor}"; Flags: nowait postinstall skipifsilent
