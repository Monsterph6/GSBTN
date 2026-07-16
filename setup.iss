#ifndef MyAppVersion
  #define MyAppVersion "0.4.0"
#endif

#define MyAppName "Giám sát dịch bệnh"
#define MyAppExeName "GiamSatDichBenh.exe"
#define MyAppPublisher "CDC Hải Phòng"

[Setup]
AppId={{4C1A50E6-6F11-4AA2-992C-C66ACCEB21C1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\GiamSatDichBenh
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=setup_output
OutputBaseFilename=GiamSatDichBenh-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\GiamSatDichBenh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài màn hình"; GroupDescription: "Biểu tượng bổ sung:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\update_cache"

[Code]
var
  ModePage: TInputOptionWizardPage;
  ServerPage: TInputQueryWizardPage;
  WorkstationPage: TInputQueryWizardPage;

function EscapeJson(Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure InitializeWizard;
begin
  ModePage := CreateInputOptionPage(
    wpSelectDir,
    'Chọn mô hình sử dụng',
    'Máy tính này sẽ hoạt động theo chế độ nào?',
    'Có thể thay đổi địa chỉ/mật khẩu trong ứng dụng. Chế độ máy chủ sẽ tự tạo CSDL riêng và chia sẻ qua mạng LAN.',
    True,
    False
  );
  ModePage.Add('Máy đơn lẻ — dùng CSDL trên máy này, không chia sẻ LAN');
  ModePage.Add('Máy trạm — kết nối tới một máy chủ trong mạng LAN');
  ModePage.Add('Máy chủ — lưu CSDL và chia sẻ cho các máy trạm');
  ModePage.SelectedValueIndex := 0;

  ServerPage := CreateInputQueryPage(
    ModePage.ID,
    'Cấu hình máy chủ',
    'Cổng và mật khẩu kết nối LAN',
    'Mật khẩu để trống nghĩa là máy trạm không cần mật khẩu. Khi Windows hỏi tường lửa, chỉ cho phép mạng Riêng tư.'
  );
  ServerPage.Add('Cổng LAN:', False);
  ServerPage.Values[0] := '8765';
  ServerPage.Add('Mật khẩu máy trạm (không bắt buộc):', True);

  WorkstationPage := CreateInputQueryPage(
    ServerPage.ID,
    'Cấu hình máy trạm',
    'Nhập địa chỉ máy chủ trong mạng LAN',
    'Ví dụ: http://192.168.1.10:8765. Có thể sửa lại trong menu Công cụ của ứng dụng.'
  );
  WorkstationPage.Add('Địa chỉ máy chủ:', False);
  WorkstationPage.Values[0] := 'http://192.168.1.10:8765';
  WorkstationPage.Add('Mật khẩu (để trống nếu không dùng):', True);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = ServerPage.ID then
    Result := ModePage.SelectedValueIndex <> 2
  else if PageID = WorkstationPage.ID then
    Result := ModePage.SelectedValueIndex <> 1;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PortValue: Integer;
begin
  Result := True;
  if (CurPageID = ServerPage.ID) and (ModePage.SelectedValueIndex = 2) then
  begin
    PortValue := StrToIntDef(ServerPage.Values[0], 0);
    if (PortValue < 1) or (PortValue > 65535) then
    begin
      MsgBox('Cổng LAN phải là số từ 1 đến 65535.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if (CurPageID = WorkstationPage.ID) and (ModePage.SelectedValueIndex = 1) then
  begin
    if (Pos('http://', Lowercase(WorkstationPage.Values[0])) <> 1) and
       (Pos('https://', Lowercase(WorkstationPage.Values[0])) <> 1) then
    begin
      MsgBox('Địa chỉ máy chủ phải bắt đầu bằng http:// hoặc https://', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure WriteDeploymentConfig;
var
  ConfigDir, ConfigPath, Mode, Port, ServerUrl, Password, Json: String;
begin
  ConfigDir := ExpandConstant('{localappdata}\CDC_HaiPhong\GiamSatDichBenh');
  ConfigPath := ConfigDir + '\deployment.json';
  ForceDirectories(ConfigDir);

  Mode := 'standalone';
  Port := '8765';
  ServerUrl := 'http://127.0.0.1:8765';
  Password := '';

  if ModePage.SelectedValueIndex = 1 then
  begin
    Mode := 'workstation';
    ServerUrl := WorkstationPage.Values[0];
    Password := WorkstationPage.Values[1];
  end
  else if ModePage.SelectedValueIndex = 2 then
  begin
    Mode := 'server';
    Port := ServerPage.Values[0];
    Password := ServerPage.Values[1];
    ServerUrl := 'http://127.0.0.1:' + Port;
  end;

  Json := '{' + #13#10 +
    '  "mode": "' + EscapeJson(Mode) + '",' + #13#10 +
    '  "server_host": "0.0.0.0",' + #13#10 +
    '  "server_port": ' + Port + ',' + #13#10 +
    '  "server_url": "' + EscapeJson(ServerUrl) + '",' + #13#10 +
    '  "password": "' + EscapeJson(Password) + '",' + #13#10 +
    '  "auto_start_server": true' + #13#10 +
    '}';
  SaveStringToFile(ConfigPath, Json, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteDeploymentConfig;
end;
