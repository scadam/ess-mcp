param([Parameter(Mandatory)][string] $Key, [Parameter(Mandatory)][string] $Text)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$body = @{ kind = 'note'; text = $Text } | ConvertTo-Json -Compress
$r = Invoke-RestMethod "$base/api/case-desk/cases/$Key/events" -Method Post -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body $body
$token = $null
"accepted=$($r.accepted)"
exit 0
