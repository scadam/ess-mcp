param([Parameter(Mandatory)][string] $Image)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
if ($Image -notmatch '^cressmcpcaldovaf61b\.azurecr\.io/ess-mcp@sha256:[0-9a-f]{64}$') { throw 'Immutable image reference required.' }
az containerapp update -n essmcp-caldova-servicenow -g essmcp-caldova-rg --image $image -o none
"update exit=$LASTEXITCODE"
az containerapp show -n essmcp-caldova-servicenow -g essmcp-caldova-rg --query "{image:properties.template.containers[0].image,ready:properties.latestReadyRevisionName,latest:properties.latestRevisionName,state:properties.provisioningState,running:properties.runningStatus}" -o json
exit 0
