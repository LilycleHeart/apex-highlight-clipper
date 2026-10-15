#ifndef PayloadInclude
  #error PayloadInclude is required
#endif

[Setup]
AppId={{AF948615-855F-4699-8640-11A9E2F08854}
AppName=Apex Highlight Clipper
AppVersion={#ProductVersion}
AppPublisher=AHC
SetupIconFile=..\electron-ui\public\brand\cat-clapperboard.ico
DefaultDirName={localappdata}\Programs\Apex Highlight Clipper
DefaultGroupName=Apex Highlight Clipper
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#InstallerOutput}
OutputBaseFilename=Apex-Clipper-{#ProductVersion}-Setup-x64
Compression=lzma2/normal
LZMANumBlockThreads=2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\app\Apex Highlight Clipper.exe
Uninstallable=not PortableMode
CreateUninstallRegKey=not PortableMode
UsePreviousAppDir=not PortableMode
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked; Check: not PortableMode

#include PayloadInclude

[Icons]
Name: "{group}\Apex Highlight Clipper"; Filename: "{app}\app\Apex Highlight Clipper.exe"; WorkingDir: "{app}"; Check: not PortableMode
Name: "{autodesktop}\Apex Highlight Clipper"; Filename: "{app}\app\Apex Highlight Clipper.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Check: not PortableMode

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\setup-ffmpeg.ps1"" -NoDownload"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Check: not PortableMode
Filename: "{app}\app\Apex Highlight Clipper.exe"; Description: "启动 Apex Highlight Clipper"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
function PortableMode: Boolean;
begin
  Result := ExpandConstant('{param:portable|0}') = '1';
end;
