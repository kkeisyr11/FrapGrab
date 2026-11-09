#ifndef AppSourceDir
  #define AppSourceDir "dist\FrapGrab"
#endif

[Setup]
AppId={{9F82C10D-57D4-4861-A792-7E823145BE1A}
AppName=Frap Grab
AppVersion=2.2.0
AppPublisher=Patryk
AppPublisherURL=https://github.com/kkeisyr11/FrapGrab
AppSupportURL=https://github.com/kkeisyr11/FrapGrab/issues
AppUpdatesURL=https://github.com/kkeisyr11/FrapGrab/releases
DefaultDirName={localappdata}\Programs\Frap Grab
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
CloseApplications=yes
OutputDir=installer
OutputBaseFilename=Frap_Grab_Setup_2.2.0
SetupIconFile=assets\icon.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Frap Grab"; Filename: "{app}\FrapGrab.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Frap Grab"; Filename: "{app}\FrapGrab.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FrapGrab.exe"; Description: "{cm:LaunchProgram,Frap Grab}"; Flags: nowait postinstall skipifsilent
