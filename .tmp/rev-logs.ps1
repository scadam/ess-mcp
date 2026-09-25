param([int] $Minutes = 12, [string] $Revision = '0000007', [int] $Last = 45)
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$lines = & 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\infra\autopilot-caldova\read-logs.ps1' -Minutes $Minutes -Take 800 -Revision $Revision 2>&1
$lines | Where-Object { $_ -notmatch 'healthz' } | Select-Object -Last $Last |
  ForEach-Object { $l = ([string]$_) -replace '(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-\.]+)', '<jwt>'; $l.Substring(0, [Math]::Min(240, $l.Length)) } |
  Out-File "$env:TEMP\ap-rev.txt" -Encoding utf8
"lines=$(@($lines).Count)"
