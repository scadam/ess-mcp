param([Parameter(Mandatory)][string] $Job, [string] $Execution = '', [int] $Minutes = 90)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Console output of a job execution from Log Analytics, through the query API (no CLI extension needed).
if (-not $Execution) { $Execution = (Get-Content ".tmp\last-$Job.txt" -Raw).Trim() }
$workspace = (az resource show -g essmcp-caldova-rg -n log-essmcp-caldova-f61b --resource-type Microsoft.OperationalInsights/workspaces --query properties.customerId -o tsv)
$token = az account get-access-token --resource 'https://api.loganalytics.io' --query accessToken -o tsv
$query = "ContainerAppConsoleLogs | where TimeGenerated > ago(${Minutes}m) | where ContainerGroupName startswith '$Execution' | project TimeGenerated, Log | order by TimeGenerated asc"
$result = Invoke-RestMethod -Method Post -Uri "https://api.loganalytics.io/v1/workspaces/$workspace/query" -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body (@{ query = $query } | ConvertTo-Json)
$token = $null
$rows = @($result.tables[0].rows)
"rows=$($rows.Count)"
$rows | ForEach-Object { $_[1] }
exit 0
