# Sobe o Prompter: garante o loopMIDI ligado e inicia o app na bandeja.
$ErrorActionPreference = "SilentlyContinue"
$loop = "C:\Program Files (x86)\Tobias Erichsen\loopMIDI\loopMIDI.exe"
if (-not (Get-Process loopMIDI)) { Start-Process $loop; Start-Sleep 2 }
Set-Location $PSScriptRoot
if ($args -contains "-console") { python app.py --sem-bandeja }
else { Start-Process pythonw -ArgumentList "app.py" -WorkingDirectory $PSScriptRoot; Write-Host "Prompter na bandeja. Tela: http://localhost:8797  Editor: http://localhost:8797/editar" }
