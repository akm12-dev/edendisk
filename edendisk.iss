; Installateur EdenDisk — compiler avec Inno Setup 6 : ISCC.exe edendisk.iss
; Construire d'abord l'exécutable : voir README (PyInstaller, src\EdenDisk.spec).

#define AppVersion "2.0.1"

[Setup]
; Identifiant inchangé depuis la 1.x : l'installation remplace l'ancienne version au lieu de s'y ajouter.
AppId={{EDENDISK-1.3.2}
AppName=EdenDisk
AppVersion={#AppVersion}
AppVerName=EdenDisk {#AppVersion}
AppPublisher=AKM12
AppPublisherURL=https://akm12.com
AppSupportURL=https://github.com/akm12-dev/releases/issues
AppUpdatesURL=https://akm12.com/logiciels/edendisk
AppCopyright=© 2025-2026 AKM12
VersionInfoVersion={#AppVersion}
VersionInfoCompany=AKM12
VersionInfoDescription=Installateur EdenDisk

DefaultDirName={autopf}\EdenDisk
DefaultGroupName=EdenDisk
DisableProgramGroupPage=yes
OutputDir=installer\output
OutputBaseFilename=EdenDisk-{#AppVersion}-setup
SetupIconFile=src\assets\icons\edendisk.ico
UninstallDisplayIcon={app}\EdenDisk.exe
UninstallDisplayName=EdenDisk

Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
CloseApplications=yes
SetupLogging=yes

WizardSmallImageFile=src\assets\icons\edendisk.png
WizardImageFile=src\assets\setup\wizard.bmp

[Languages]
Name: "french";  MessagesFile: "compiler:Languages\French.isl"; LicenseFile: "licence\fr\licence.txt"
Name: "english"; MessagesFile: "compiler:Default.isl";          LicenseFile: "licence\en\license.txt"

[Files]
Source: "src\dist\EdenDisk.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "licence\fr\licence.txt"; DestDir: "{app}"; DestName: "Licence.txt"; Languages: french
Source: "licence\en\license.txt"; DestDir: "{app}"; DestName: "License.txt"; Languages: english

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Icons]
Name: "{group}\EdenDisk"; Filename: "{app}\EdenDisk.exe"
Name: "{autodesktop}\EdenDisk"; Filename: "{app}\EdenDisk.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\EdenDisk.exe"; Description: "{cm:LaunchProgram,EdenDisk}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: dirifempty; Name: "{app}"
