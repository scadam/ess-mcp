$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$lines = & 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\infra\autopilot-caldova\read-logs.ps1' -Minutes 45 -Take 400
$lines | Out-File "$env:TEMP\ap-logs.txt" -Encoding utf8
"total lines: $(@($lines).Count)"
$lines | Where-Object { $_ -match '(?i)api/messages|bot\.|activity|agentic|msal|AADSTS|error|exception|traceback|warning|rejected|401|403|500|compliance|on_message|conversation' } |
  Where-Object { $_ -notmatch 'GET /healthz' } | Select-Object -Last 60 |
  ForEach-Object { $l = $_ -replace '(?i)(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-\.]+)', '<jwt>'; $l.Substring(0, [Math]::Min(330, $l.Length)) }
