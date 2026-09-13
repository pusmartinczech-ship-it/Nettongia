#define MyAppName "OpenPDF Editor"
#define MyAppVersion GetEnv("OPENPDF_VERSION")
#define MyAppExeName "OpenPDFEditor.exe"

[Setup]
AppId={{3F9060A8-2B62-4F6D-BB67-D5C3D05D4057}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=OpenPDF Editor contributors
DefaultDirName={autopf}\OpenPDF Editor
DefaultGroupName=OpenPDF Editor
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=OpenPDF_Editor_{#MyAppVersion}-x64
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
Source: "..\dist\OpenPDFEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OpenPDF Editor"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\OpenPDF Editor"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,OpenPDF Editor}"; Flags: nowait postinstall skipifsilent
