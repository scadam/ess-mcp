param([Parameter(Mandatory)][string] $Instance, [Parameter(Mandatory)][string] $Scenario)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Launch a skill on an instance from the control plane; the result is delivered to the manager in Teams.
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$body = @{ scenario = $Scenario; prompt = $Scenario } | ConvertTo-Json -Compress
$r = Invoke-RestMethod "$base/api/agentic-instances/$Instance/run" -Method Post -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body $body
$token = $null
"status=$($r.status) runId=$($r.runId) caseKey=$($r.caseKey)"
exit 0
