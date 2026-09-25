$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$sub = '54b04cf7-73f7-4ea0-aa82-b15694ea8033'
$saId = "/subscriptions/$sub/resourceGroups/essmcp-caldova-rg/providers/Microsoft.Storage/storageAccounts/stautopilotcaldova78f0"
"--- policy states on the storage account"
$states = az policy state list --resource $saId --query "[].{def:policyDefinitionName, action:policyDefinitionAction, state:complianceState, assignment:policyAssignmentName, ref:policyDefinitionReferenceId}" -o json 2>$null | ConvertFrom-Json
$states | Where-Object { $_.action -in 'modify', 'deny', 'deployifnotexists', 'append' -or $_.state -eq 'NonCompliant' } | Select-Object -First 15 | ForEach-Object { "{0} | {1} | {2} | {3} | {4}" -f $_.action, $_.state, $_.assignment, $_.def, $_.ref }
"--- assignments that mention storage/public/network"
$assign = az policy assignment list --disable-scope-strict-match --scope "/subscriptions/$sub/resourceGroups/essmcp-caldova-rg" --query "[].{name:name, display:displayName, scope:scope, enforcement:enforcementMode}" -o json | ConvertFrom-Json
$assign | Where-Object { $_.display -match '(?i)storage|public|network|secure|baseline|benchmark|MCSB|Microsoft cloud' } | ForEach-Object { "{0} | {1} | {2} | {3}" -f $_.display, $_.enforcement, $_.name, $_.scope }
"--- Container Apps environment networking"
az containerapp env show -g essmcp-caldova-rg -n cae-essmcp-caldova-f61b2 --query "{vnet:properties.vnetConfiguration, staticIp:properties.staticIp, profiles:properties.workloadProfiles[].name, publicAccess:properties.publicNetworkAccess}" -o json
"--- recent storage writes (caller, policy)"
az monitor activity-log list --resource-id $saId --offset 14h --query "[?operationName.value=='Microsoft.Storage/storageAccounts/write' || contains(operationName.value, 'policies')].{t:eventTimestamp, op:operationName.value, who:caller, status:status.value}" -o tsv 2>$null | Select-Object -First 12
