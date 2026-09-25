$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
foreach ($i in 1..30) {
  $app = az containerapp show -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "{rev:properties.latestRevisionName, ready:properties.latestReadyRevisionName}" -o json | ConvertFrom-Json
  if ($app.rev -eq $app.ready) { break }
  Start-Sleep -Seconds 10
}
"latest=$($app.rev) ready=$($app.ready)"
az containerapp revision list -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "[?properties.active].{name:name, health:properties.healthState, traffic:properties.trafficWeight, replicas:properties.replicas}" -o json | ConvertFrom-Json | ForEach-Object { "{0} health={1} traffic={2} replicas={3}" -f $_.name, $_.health, $_.traffic, $_.replicas }
$envs = az containerapp show -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "properties.template.containers[0].env[?name=='CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID' || name=='ENTRA_AGENT_BLUEPRINT_CLIENT_ID'].{n:name, v:value}" -o json | ConvertFrom-Json
$envs | ForEach-Object { "{0}={1}" -f $_.n, $_.v }
$secret = az containerapp show -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "properties.configuration.secrets[].keyVaultUrl" -o tsv
"secretRef=$secret"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$id = Invoke-RestMethod "$base/api/identity" -Headers @{ Authorization = "Bearer $tok" } -TimeoutSec 30
$tok = $null
$bp = $id.blueprint
"identity: agent=$($id.agentName) blueprint=$($bp.clientId) sdkConfigured=$($id.sdkConfigured) lastError=$($id.lastError)"
