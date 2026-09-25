param([Parameter(Mandatory)][string] $Query)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$workspace = (az resource show -g essmcp-caldova-rg -n log-essmcp-caldova-f61b --resource-type Microsoft.OperationalInsights/workspaces --query properties.customerId -o tsv)
$token = az account get-access-token --resource 'https://api.loganalytics.io' --query accessToken -o tsv
$result = Invoke-RestMethod -Method Post -Uri "https://api.loganalytics.io/v1/workspaces/$workspace/query" -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body (@{ query = $Query } | ConvertTo-Json)
$token = $null
$columns = @($result.tables[0].columns | ForEach-Object { $_.name })
"columns=$($columns -join ',') rows=$(@($result.tables[0].rows).Count)"
foreach ($row in @($result.tables[0].rows)) { ($row | ForEach-Object { "$_" }) -join ' | ' }
exit 0
