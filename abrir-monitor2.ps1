param([string]$Url = "http://localhost:8797")
# Abre o prompter em tela cheia no segundo monitor (ou no primeiro, se so houver um).
Add-Type -AssemblyName System.Windows.Forms
$screens = [System.Windows.Forms.Screen]::AllScreens
$target = $screens | Where-Object { -not $_.Primary } | Select-Object -First 1
if (-not $target) { $target = [System.Windows.Forms.Screen]::PrimaryScreen }
$b = $target.Bounds
$edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" }
$profile = Join-Path $env:LOCALAPPDATA "PrompterKiosk"
$args = @("--app=$Url", "--user-data-dir=$profile", "--window-position=$($b.X),$($b.Y)", "--window-size=$($b.Width),$($b.Height)", "--start-fullscreen", "--no-first-run", "--disable-session-crashed-bubble", "--autoplay-policy=no-user-gesture-required")
Start-Process $edge -ArgumentList $args
