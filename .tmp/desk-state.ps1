$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$desk = Invoke-RestMethod "$base/api/case-desk" -Headers @{ Authorization = "Bearer $token" }
$token = $null
"bindings:"
$desk.bindings | ForEach-Object { "  $($_.function) | $($_.name) | $($_.system) | $($_.skill) | queue=$($_.queue) | teams=$($_.hasTeamsIdentity)" }
"counts: $($desk.counts | ConvertTo-Json -Compress)"
"eventSources: $($desk.eventSources | ConvertTo-Json -Compress)"
"cases:"
$desk.cases | ForEach-Object { "  " + ($_ | ConvertTo-Json -Compress -Depth 4) }
exit 0
