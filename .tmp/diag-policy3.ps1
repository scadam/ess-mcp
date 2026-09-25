$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$sub = '54b04cf7-73f7-4ea0-aa82-b15694ea8033'
$all = az policy assignment list --disable-scope-strict-match --scope "/subscriptions/$sub" -o json | ConvertFrom-Json
$mcaps = $all | Where-Object { $_.name -eq 'MCAPSGovDeployPolicies' } | Select-Object -First 1
"assignment scope=$($mcaps.scope) enforcement=$($mcaps.enforcementMode)"
"set=$($mcaps.policyDefinitionId)"
$setOut = New-TemporaryFile
az rest --method GET --url "https://management.azure.com$($mcaps.policyDefinitionId)" --url-parameters 'api-version=2023-04-01' --output-file $setOut 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { 'set read failed'; return }
$set = Get-Content $setOut -Raw | ConvertFrom-Json
$ref = $set.properties.policyDefinitions | Where-Object { $_.policyDefinitionReferenceId -eq 'StorageAccount_PublicNetwork_Modify' }
"def=$($ref.policyDefinitionId)"
"refParams=" + ($ref.parameters | ConvertTo-Json -Depth 4 -Compress)
$defOut = New-TemporaryFile
az rest --method GET --url "https://management.azure.com$($ref.policyDefinitionId)" --url-parameters 'api-version=2023-04-01' --output-file $defOut 2>&1 | Out-Null
$def = Get-Content $defOut -Raw | ConvertFrom-Json
"display=$($def.properties.displayName)"
"if=" + ($def.properties.policyRule.if | ConvertTo-Json -Depth 10 -Compress)
"ops=" + ($def.properties.policyRule.then.details.operations | ConvertTo-Json -Depth 5 -Compress)
Remove-Item $setOut, $defOut -ErrorAction SilentlyContinue
