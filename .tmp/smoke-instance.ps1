$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $room = Invoke-RestMethod "$base/api/control-room?refresh=1" -Headers $h -TimeoutSec 60
  "persistence: " + ($room.persistence | ConvertTo-Json -Compress -Depth 3)
  "instances: $(@($room.instances).Count)"
  foreach ($i in @($room.instances)) {
    "  {0} | key={1} | state={2} | manager={3} | compliance={4} | policy={5} skills={6} servers={7}" -f $i.name, $i.key, $i.presence.state, $i.manager, [bool]$i.compliance, $i.policy.source, (@($i.policy.skills) -join ','), (@($i.policy.servers) -join ',')
  }
  $cases = Invoke-RestMethod "$base/api/compliance/cases" -Headers $h -TimeoutSec 30
  "compliance configured=$($cases.configured) cases=$(@($cases.cases).Count)"
} finally { $tok = $null; $h = $null }
