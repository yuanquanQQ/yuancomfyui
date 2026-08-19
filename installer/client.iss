#define AppName "YunComfyUI Client"
#define AppVersion "1.0.0"
#define AppPublisher "YunComfyUI"
#define AppExeName "yuncomfyui.exe"

[Setup]
AppId={{9D92E56C-249E-4749-A689-CC6A36E20F6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\YunComfyUI\Client
DefaultGroupName=YunComfyUI
AllowNoIcons=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=YunComfyUI-Client-Setup
SetupIconFile=assets\client-icon.ico
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
Source: "..\client\dist\yuncomfyui.exe"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\.license"; Permissions: users-modify
Name: "{app}\profiles"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\uploads"; Permissions: users-modify
Name: "{app}\outputs"; Permissions: users-modify
Name: "{app}\library"; Permissions: users-modify
Name: "{app}\works"; Permissions: users-modify

[Icons]
Name: "{group}\YunComfyUI Client"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\YunComfyUI Client"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 YunComfyUI 客户端"; Flags: nowait postinstall skipifsilent
