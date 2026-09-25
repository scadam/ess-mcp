param([string] $Url = 'http://127.0.0.1:8765/control-plane.html', [string] $Out = 'ui-shot.png', [int] $Width = 1600, [int] $Height = 1100)
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$path = Join-Path 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\.tmp' $Out
$profile = Join-Path $env:TEMP 'ap-edge-shot'
& $edge --headless=new --disable-gpu --hide-scrollbars --no-first-run --user-data-dir="$profile" --window-size="$Width,$Height" --virtual-time-budget=5000 --screenshot="$path" $Url 2>$null | Out-Null
Start-Sleep -Milliseconds 300
if (Test-Path $path) { "saved $path $((Get-Item $path).Length)" } else { 'no screenshot' }
