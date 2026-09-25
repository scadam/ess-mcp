$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 30
  "template: " + ($room.template | ConvertTo-Json -Depth 2 -Compress).Substring(0, [Math]::Min(420, ($room.template | ConvertTo-Json -Depth 2 -Compress).Length))
  "instances: $(@($room.instances).Count)"
  "servers: " + ((@($room.servers) | ForEach-Object { "{0}:{1}:{2}" -f $_.key, $_.status, $_.tools }) -join '  ')
  $skills = Invoke-RestMethod "$base/api/skills" -Headers $h -TimeoutSec 30
  $c = @($skills) | Where-Object { $_.name -eq 'compliance-case-resolution' } | Select-Object -First 1
  "compliance skill: " + ($c | ConvertTo-Json -Depth 3 -Compress).Substring(0, [Math]::Min(500, ($c | ConvertTo-Json -Depth 3 -Compress).Length))
} finally { $tok = $null; $h = $null }
