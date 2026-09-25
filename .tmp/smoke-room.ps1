$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
try {
  $room = Invoke-RestMethod "$base/api/control-room" -Headers @{ Authorization = "Bearer $tok" } -TimeoutSec 60
  "fleet: " + ($room.fleet | ConvertTo-Json -Compress)
  "template: state=$($room.template.presence.state) text=$($room.template.presence.text) fleetAggregate=$($room.template.summary.fleetAggregate) counts=$($room.template.summary.counts | ConvertTo-Json -Compress)"
  foreach ($i in @($room.instances)) { "instance: $($i.name) state=$($i.presence.state) text=$($i.presence.text) openCases=$($i.cases.open)" }
  $css = (Invoke-WebRequest "$base/static/autopilot-theme.css" -UseBasicParsing -TimeoutSec 30)
  "theme css cache-control=$($css.Headers['Cache-Control'])"
} finally { $tok = $null }
