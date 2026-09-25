$ErrorActionPreference = 'Continue'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$rg = '/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg'
'== perimeters'
az resource list -g essmcp-caldova-rg --resource-type Microsoft.Network/networkSecurityPerimeters --query "[].name" -o tsv
foreach ($p in (az resource list -g essmcp-caldova-rg --resource-type Microsoft.Network/networkSecurityPerimeters --query "[].name" -o tsv)) {
  "== $p associations"
  az rest --method get --url "https://management.azure.com$rg/providers/Microsoft.Network/networkSecurityPerimeters/$p/resourceAssociations" --url-parameters 'api-version=2024-07-01' --query "value[].{name:name,mode:properties.accessMode,resource:properties.privateLinkResource.id}" -o json
}
'== kv network'
az keyvault show -n kv-essmcp-caldova-f61b --query "{public:properties.publicNetworkAccess, acls:properties.networkAcls}" -o json
'== policy assignments mentioning key vault'
az policy assignment list --scope $rg --disable-scope-strict-match --query "[?contains(to_string(displayName), 'ey')].{name:displayName, enforcement:enforcementMode}" -o table
exit 0
