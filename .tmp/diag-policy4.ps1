$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$saId = '/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg/providers/Microsoft.Storage/storageAccounts/stautopilotcaldova78f0'
$states = az policy state list --resource $saId -o json | ConvertFrom-Json
$s = $states | Where-Object { $_.policyDefinitionReferenceId -eq 'storageaccountpublicnetworkmodify' } | Select-Object -First 1
"assignmentId=$($s.policyAssignmentId)"
"setId=$($s.policySetDefinitionId)"
"defId=$($s.policyDefinitionId)"
$out = New-TemporaryFile
az rest --method GET --url "https://management.azure.com$($s.policyDefinitionId)" --url-parameters 'api-version=2023-04-01' --output-file $out 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  $def = Get-Content $out -Raw | ConvertFrom-Json
  "display=$($def.properties.displayName)"
  "if=" + ($def.properties.policyRule.if | ConvertTo-Json -Depth 10 -Compress)
  "ops=" + ($def.properties.policyRule.then.details.operations | ConvertTo-Json -Depth 5 -Compress)
} else { 'definition read failed' }
az rest --method GET --url "https://management.azure.com$($s.policyAssignmentId)" --url-parameters 'api-version=2023-04-01' --output-file $out 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { $a = Get-Content $out -Raw | ConvertFrom-Json; "assignment display=$($a.properties.displayName) enforcement=$($a.properties.enforcementMode) notScopes=$(@($a.properties.notScopes).Count)" } else { 'assignment read failed' }
Remove-Item $out -ErrorAction SilentlyContinue
