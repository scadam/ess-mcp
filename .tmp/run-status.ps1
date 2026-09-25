param([Parameter(Mandatory)][string] $RunId)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$runs = Invoke-RestMethod "$base/api/runs" -Headers @{ Authorization = "Bearer $token" }
$token = $null
$run = @($runs) + @($runs.runs) | Where-Object { $_ -and $_.id -eq $RunId } | Select-Object -First 1
if (-not $run) { "run not found"; exit 0 }
"status=$($run.status) title=$($run.title)"
"delivery=$($run.delivery | ConvertTo-Json -Compress -Depth 4)"
if ($run.runFiles) { "runFiles=$($run.runFiles | ConvertTo-Json -Depth 5)" } else { "runFiles=(none)" }
$result = [string]$run.result
"result chars=$($result.Length)"
$result.Substring(0, [Math]::Min(1500, $result.Length))
exit 0
