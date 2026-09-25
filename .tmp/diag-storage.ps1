$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$sa = az storage account show -g essmcp-caldova-rg -n stautopilotcaldova78f0 -o json | ConvertFrom-Json
"publicNetworkAccess=$($sa.publicNetworkAccess) defaultAction=$($sa.networkRuleSet.defaultAction) bypass=$($sa.networkRuleSet.bypass) ipRules=$(@($sa.networkRuleSet.ipRules).Count) vnetRules=$(@($sa.networkRuleSet.virtualNetworkRules).Count) sharedKey=$($sa.allowSharedKeyAccess) privateEndpoints=$(@($sa.privateEndpointConnections).Count)"
$ra = az role assignment list --scope $sa.id --include-inherited --assignee 22fcc9d8-e467-4601-8983-6b41fb3656cc --query "[].{role:roleDefinitionName, scope:scope}" -o json | ConvertFrom-Json
$ra | ForEach-Object { "role: {0} @ {1}" -f $_.role, ($_.scope -replace '^.*/providers/', '') }
$ra2 = az role assignment list --all --assignee 22fcc9d8-e467-4601-8983-6b41fb3656cc --query "[?contains(scope, 'stautopilotcaldova78f0')].{role:roleDefinitionName, scope:scope}" -o json | ConvertFrom-Json
$ra2 | ForEach-Object { "role(all): {0} @ {1}" -f $_.role, ($_.scope -replace '^.*/storageAccounts/', '') }
az monitor activity-log list -g essmcp-caldova-rg --offset 12h --query "[?contains(resourceId, 'stautopilotcaldova78f0') && operationName.value=='Microsoft.Storage/storageAccounts/write'].{t:eventTimestamp, who:caller, status:status.value}" -o tsv 2>$null | Select-Object -First 8
