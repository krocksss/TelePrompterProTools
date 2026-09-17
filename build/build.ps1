# Gera o instalador do Prompter no Windows: PyInstaller (dist\Prompter\) + Inno Setup (dist\PrompterSetup-<versao>.exe)
# Uso: .\build\build.ps1                 (tudo)
#      .\build\build.ps1 -SoInstalador   (pula o PyInstaller, so empacota)
# No macOS use build/mac/build.sh
param([switch]$SoInstalador)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:PYTHONUTF8 = "1"
$ver = (Select-String -Path "$root\app.py" -Pattern 'VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Prompter $ver"
if (-not (Test-Path "$root\build\vendor\loopMIDISetup.exe")) { throw "falta build\vendor\loopMIDISetup.exe (instalador oficial do loopMIDI, zip em tobias-erichsen.de)" }

if (-not $SoInstalador) {
  if (Test-Path "$root\dist\Prompter") { Remove-Item -Recurse -Force "$root\dist\Prompter" }
  python -m PyInstaller --noconfirm --clean --distpath "$root\dist" --workpath "$root\build\work" "$root\build\prompter.spec"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }
  Get-ChildItem "$root\dist\Prompter\_internal" -Recurse -Directory -Include "tests","test","__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  $size = [math]::Round((Get-ChildItem "$root\dist\Prompter" -Recurse | Measure-Object Length -Sum).Sum / 1MB)
  Write-Host "dist\Prompter: $size MB"
}

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup nao encontrado (winget install JRSoftware.InnoSetup)" }
& $iscc "/DAppVersion=$ver" "$root\build\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }
Get-Item "$root\dist\PrompterSetup-$ver.exe" | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB)}}
