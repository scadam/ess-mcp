$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  try {
    Invoke-RestMethod "$base/api/control-room/reset" -Method Post -Headers $h -ContentType 'application/json' -Body '{"confirm":"no"}' -TimeoutSec 30 | Out-Null
    'reset without confirmation: UNEXPECTED success'
  } catch { "reset without confirmation: HTTP $([int]$_.Exception.Response.StatusCode) (expected 400)" }
  $room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 60
  foreach ($i in @($room.instances)) { "tile: {0} kind={1} state={2}" -f $i.name, $i.kind, $i.presence.state }
  "template: $($room.template.presence.text)"
  $html = (Invoke-WebRequest "$base/control-plane" -Headers $h -UseBasicParsing -TimeoutSec 30).Content
  "reset button served: $($html.Contains('id=""crReset""'))"
} finally { $tok = $null; $h = $null }
