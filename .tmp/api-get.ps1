param([Parameter(Mandatory)][string] $Path, [int] $Depth = 6, [string] $Method = 'GET', [string] $Body = '')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token" }
if ($Method -eq 'GET') { $r = Invoke-RestMethod "$base$Path" -Headers $headers }
else { $r = Invoke-RestMethod "$base$Path" -Method $Method -Headers $headers -ContentType 'application/json' -Body $Body }
$r | ConvertTo-Json -Depth $Depth
