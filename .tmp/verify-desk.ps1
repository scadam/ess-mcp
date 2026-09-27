$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
. .\infra\demo\environment.ps1
# Reads the control room as the operator and prints the desk's startup event (names only; no tokens printed).
$token = Get-DemoOperatorToken
try {
  $room = Invoke-RestMethod "$DemoHostUrl/api/control-room/activity" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 60
} finally { $token = $null }
"keys: " + (($room.PSObject.Properties.Name) -join ', ')
$json = $room | ConvertTo-Json -Depth 12 -Compress
$hits = [regex]::Matches($json, '"[^"]*case desk is listening[^"]*"[^{}]{0,600}')
"listening events: $($hits.Count)"
$hits | Select-Object -First 1 | ForEach-Object { $_.Value.Substring(0, [Math]::Min(600, $_.Value.Length)) }
exit 0
