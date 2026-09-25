$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
az containerapp revision list -n essmcp-caldova-servicenow -g essmcp-caldova-rg --query "[].{name:name,active:properties.active,traffic:properties.trafficWeight,health:properties.healthState,state:properties.runningState,prov:properties.provisioningState,replicas:properties.replicas,created:properties.createdTime}" -o json
exit 0
