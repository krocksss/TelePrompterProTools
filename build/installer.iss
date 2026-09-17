; Instalador do Prompter (Inno Setup 6). Compilado por build\build.ps1 com /DAppVersion=x.y.z
; Inclui o loopMIDI (Tobias Erichsen, instalador oficial, silencioso) e cria a porta "Pro Tools MTC".
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppName "Prompter"
#define Root ".."

[Setup]
AppId={{7C1E5D2A-5B1A-4E7B-9D2F-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Marllon Machado (github.com/krocksss)
AppPublisherURL=https://github.com/krocksss
AppSupportURL=https://github.com/krocksss/TelePrompterProTools
AppUpdatesURL=https://github.com/krocksss/TelePrompterProTools/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=admin
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
OutputDir={#Root}\dist
OutputBaseFilename=PrompterSetup-{#AppVersion}
SetupIconFile={#Root}\static\prompter.ico
UninstallDisplayIcon={app}\Prompter.exe
WizardImageFile={#Root}\build\wizard.bmp
WizardSmallImageFile={#Root}\build\wizard-small.bmp
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
WelcomeLabel1=Prompter · teleprompter sincronizado com o Pro Tools
WelcomeLabel2=Feito por Marllon Machado (github.com/krocksss).%n%nEste assistente instala o Prompter e o loopMIDI (porta MIDI virtual para o timecode do Pro Tools). Basta clicar em Instalar.%n%nDepois, é só abrir o Prompter: ele abre o Pro Tools junto e a tela do teleprompter no navegador.

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "autostart"; Description: "Iniciar o Prompter com o Windows (fica na bandeja)"; GroupDescription: "No show:"; Flags: unchecked

[Files]
; DLLs de runtime nao mudam entre versoes: so instala se faltar (evita "arquivo em uso" quando outro programa as carregou)
; exclusao ANCORADA na raiz de _internal (barra inicial): sem isso pegava numpy.libs\msvcp140-<hash>.dll e o NumPy quebrava
Source: "{#Root}\dist\Prompter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "\_internal\msvcp140.dll,\_internal\MSVCP140_1.dll,\_internal\MSVCP140_ATOMIC_WAIT.dll,\_internal\vcruntime140.dll,\_internal\vcruntime140_1.dll"
; DLLs de runtime da Microsoft: iguais em toda versao, so instala se faltar (evita "arquivo em uso")
Source: "{#Root}\dist\Prompter\_internal\msvcp140.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "{#Root}\dist\Prompter\_internal\MSVCP140_1.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "{#Root}\dist\Prompter\_internal\MSVCP140_ATOMIC_WAIT.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "{#Root}\dist\Prompter\_internal\vcruntime140.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "{#Root}\dist\Prompter\_internal\vcruntime140_1.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "{#Root}\build\vendor\loopMIDISetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Prompter.exe"
Name: "{group}\Configuração do Prompter"; Filename: "http://localhost:8797/config"
Name: "{group}\Desinstalar o {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Prompter.exe"; Tasks: desktopicon

[Registry]
; porta MIDI virtual do loopMIDI (lida pelo loopMIDI ao abrir) e autostart do loopMIDI, no perfil do usuário
Root: HKCU; Subkey: "Software\Tobias Erichsen\loopMIDI\Ports"; ValueType: dword; ValueName: "Pro Tools MTC"; ValueData: 1; Flags: createvalueifdoesntexist
Root: HKCU; Subkey: "Software\Tobias Erichsen\loopMIDI"; ValueType: dword; ValueName: "autostart"; ValueData: 1
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "loopMIDI"; ValueData: """{commonpf32}\Tobias Erichsen\loopMIDI\loopMIDI.exe"""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Prompter"; ValueData: """{app}\Prompter.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
; loopMIDI: instalador oficial (WiX Burn) em modo silencioso, só se ainda não existe
Filename: "{tmp}\loopMIDISetup.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Instalando o loopMIDI (porta MIDI virtual)…"; Flags: waituntilterminated; Check: not LoopMidiInstalled
Filename: "{commonpf32}\Tobias Erichsen\loopMIDI\loopMIDI.exe"; Flags: nowait runasoriginaluser skipifdoesntexist; Check: not LoopMidiRunning
Filename: "{app}\Prompter.exe"; Parameters: "--primeira-vez"; Description: "Abrir o Prompter agora (abre o Pro Tools junto)"; Flags: nowait postinstall skipifsilent runasoriginaluser
; atualizacao silenciosa (feita pelo proprio Prompter): reabre o app ao terminar
Filename: "{app}\Prompter.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM Prompter.exe"; Flags: runhidden; RunOnceId: "killprompter"

[Code]
function LoopMidiInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf32}\Tobias Erichsen\loopMIDI\loopMIDI.exe'));
end;

function LoopMidiRunning: Boolean;
var R: Integer;
begin
  Result := Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq loopMIDI.exe" | find /I "loopMIDI.exe" >nul', '', SW_HIDE, ewWaitUntilTerminated, R) and (R = 0);
end;

function PrompterRunning: Boolean;
var R: Integer;
begin
  Result := Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq Prompter.exe" | find /I "Prompter.exe" >nul', '', SW_HIDE, ewWaitUntilTerminated, R) and (R = 0);
end;

// fecha o Prompter por conta propria, espera sumir e so entao copia os arquivos.
// SEM /T: o Pro Tools e este proprio instalador (quando o Prompter baixa e roda a atualizacao) sao FILHOS do
// Prompter.exe; matar a arvore fechava o Pro Tools e o instalador morria no meio (2.0.16 -> 2.0.17 travou assim).
// O trabalhador do demucs tambem se chama Prompter.exe, entao /IM ja pega ele.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var R, i: Integer;
begin
  Exec('taskkill', '/F /IM Prompter.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  for i := 1 to 30 do begin
    if not PrompterRunning then break;
    Sleep(500);
  end;
  Sleep(1500);
  if not LoopMidiInstalled then Exec('taskkill', '/F /IM loopMIDI.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
