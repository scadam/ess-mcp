$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$sub = '54b04cf7-73f7-4ea0-aa82-b15694ea8033'
$list = az rest --method GET --url "https://management.azure.com/subscriptions/$sub/providers/Microsoft.Authorization/policyAssignments" --url-parameters 'api-version=2023-04-01' '$filter=atScope()' -o json | ConvertFrom-Json
$mcaps = $list.value | Where-Object { $_.name -eq 'MCAPSGovDeployPolicies' } | Select-Object -First 1
"assignment id=$($mcaps.id)"
"set=$($mcaps.properties.policyDefinitionId) enforcement=$($mcaps.properties.enforcementMode)"
$set = az rest --method GET --url "https://management.azure.com$($mcaps.properties.policyDefinitionId)" --url-parameters 'api-version=2023-04-01' -o json 2>&1
if ($LASTEXITCODE -ne 0) { "set read failed: $(($set | Out-String).Substring(0, 200))"; return }
$set = $set | Out-String | ConvertFrom-Json
$ref = $set.properties.policyDefinitions | Where-Object { $_.policyDefinitionReferenceId -eq 'StorageAccount_PublicNetwork_Modify' }
"def=$($ref.policyDefinitionId)"
$def = az rest --method GET --url "https://management.azure.com$($ref.policyDefinitionId)" --url-parameters 'api-version=2023-04-01' -o json | Out-String | ConvertFrom-Json
"display=$($def.properties.displayName)"
"if=" + ($def.properties.policyRule.if | ConvertTo-Json -Depth 10 -Compress)
"ops=" + ($def.properties.policyRule.then.details.operations | ConvertTo-Json -Depth 5 -Compress)
"params=" + (($ref.parameters | ConvertTo-Json -Depth 4 -Compress) -replace '\s+', ' ')
