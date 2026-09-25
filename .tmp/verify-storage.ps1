$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$sa = az storage account show -g essmcp-caldova-rg -n stautopilotcaldova78f0 -o json | ConvertFrom-Json
"storage publicNetworkAccess=$($sa.publicNetworkAccess) defaultAction=$($sa.networkRuleSet.defaultAction)"
$assoc = az rest --method GET --url "https://management.azure.com/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg/providers/Microsoft.Network/networkSecurityPerimeters/nsp-autopilot-caldova-78f0/resourceAssociations/autopilot-state-storage" --url-parameters 'api-version=2024-07-01' -o json | ConvertFrom-Json
"association accessMode=$($assoc.properties.accessMode) state=$($assoc.properties.provisioningState) hasProvisioningIssues=$($assoc.properties.hasProvisioningIssues)"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
try {
  $r = Invoke-WebRequest "$base/api/compliance/cases" -Headers @{ Authorization = "Bearer $tok" } -UseBasicParsing -TimeoutSec 60 -SkipHttpErrorCheck
  "compliance cases -> $($r.StatusCode) $(([string]$r.Content).Substring(0, [Math]::Min(120, ([string]$r.Content).Length)))"
} finally { $tok = $null }
