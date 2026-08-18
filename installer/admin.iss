#define AppName "YunComfyUI License Admin"
#define AppVersion "1.0.0"
#define AppPublisher "YunComfyUI"
#define AppExeName "YunComfyUI-License-Admin.exe"

[Setup]
AppId={{6C42390C-785E-4911-9F3F-28B768E96DF8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\YunComfyUI\Admin
DefaultGroupName=YunComfyUI
AllowNoIcons=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=YunComfyUI-Admin-Setup
SetupIconFile=assets\admin-icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DisableProgramGroupPage=auto

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "..\admin\dist\YunComfyUI-License-Admin.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\YunComfyUI License Admin"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\YunComfyUI License Admin"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 YunComfyUI 授权管理端"; Flags: nowait postinstall skipifsilent
