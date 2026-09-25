[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('servicenow', 'salesforce')][string] $System,
  [Parameter(Mandatory)][ValidateSet('setup', 'demo', 'reset')][string] $Mode,
  # ServiceNow demo incidents to raise or close; default both.
  [ValidateSet('battery', 'lockout')][string[]] $Scenario = @()
)
# Runs one provisioning mode as a Container Apps job from the MCP server's own image. Credentials, the webhook key
# and the demo sign-in password reach the job only as Key Vault references.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription

$job = "job-desk-$System"
$source = az containerapp show -g $DemoResourceGroup -n "essmcp-caldova-$System" -o json | ConvertFrom-Json
$image = $source.properties.template.containers[0].image
if ($image -notmatch "^$([regex]::Escape($DemoRegistry))/ess-mcp@sha256:[0-9a-f]{64}$") {
  throw "essmcp-caldova-$System does not run an immutable ess-mcp image ($image)."
}
$identity = @($source.identity.userAssignedIdentities.PSObject.Properties.Name)[0]
$vault = "https://$DemoVault.vault.azure.net/secrets"
$secrets = @($source.properties.configuration.secrets | ForEach-Object { @{ name = $_.name; keyVaultUrl = $_.keyVaultUrl; identity = $identity } })
$secrets += @{ name = 'webhook-secret'; keyVaultUrl = "$vault/autopilot-webhook-$System"; identity = $identity }
$variables = @($source.properties.template.containers[0].env | ForEach-Object {
  if ($_.secretRef) { @{ name = $_.name; secretRef = $_.secretRef } } else { @{ name = $_.name; value = $_.value } } })
$variables += @{ name = 'AUTOPILOT_HOST_URL'; value = $DemoHostUrl }
$variables += @{ name = 'AUTOPILOT_WEBHOOK_SECRET'; secretRef = 'webhook-secret' }
if ($System -eq 'servicenow' -and (Test-DemoVaultSecret 'servicenow-demo-user-password')) {
  $secrets += @{ name = 'demo-user-password'; keyVaultUrl = "$vault/servicenow-demo-user-password"; identity = $identity }
  $variables += @{ name = 'AUTOPILOT_DEMO_USER_PASSWORD'; secretRef = 'demo-user-password' }
}
$definition = @{
  location = $source.location
  identity = @{ type = 'UserAssigned'; userAssignedIdentities = @{ $identity = @{} } }
  properties = @{
    environmentId = $source.properties.environmentId
    workloadProfileName = 'Consumption'
    configuration = @{
      triggerType = 'Manual'; replicaTimeout = 1800; replicaRetryLimit = 0
      manualTriggerConfig = @{ parallelism = 1; replicaCompletionCount = 1 }
      secrets = $secrets
      registries = @(@{ server = $DemoRegistry; identity = $identity })
    }
    template = @{ containers = @(@{
      name = 'provision'; image = $image
      command = @('python', '-m', "mcp_servers.provisioning.$System"); args = @(@($Mode) + $Scenario)
      env = $variables; resources = @{ cpu = 0.5; memory = '1Gi' }
    }) }
  }
}
$file = Join-Path ([IO.Path]::GetTempPath()) "$job-$PID.yaml"
try {
  $definition | ConvertTo-Json -Depth 12 | Set-Content -Path $file -Encoding utf8
  $exists = az containerapp job show -g $DemoResourceGroup -n $job --query name -o tsv 2>$null
  $verb = if ($exists) { 'update' } else { 'create' }
  az containerapp job $verb -g $DemoResourceGroup -n $job --yaml $file -o none
  if ($LASTEXITCODE -ne 0) { throw "Could not $verb the $job job." }
} finally {
  Remove-Item $file -Force -ErrorAction SilentlyContinue
}
$execution = az containerapp job start -g $DemoResourceGroup -n $job --query name -o tsv
if (-not $execution) { throw "The $job job did not start." }
Write-Host "$System $Mode $($Scenario -join ' ') -> $execution" -NoNewline
$status = ''
foreach ($i in 1..120) {
  Start-Sleep -Seconds 10
  $status = az containerapp job execution show -g $DemoResourceGroup -n $job --job-execution-name $execution --query properties.status -o tsv
  if ($status -in 'Succeeded', 'Failed', 'Stopped', 'Degraded') { break }
  Write-Host '.' -NoNewline
}
Write-Host " $status"
if ($status -ne 'Succeeded') {
  throw "$job execution $execution ended $status. Its log is in Log Analytics (ContainerAppConsoleLogs, ContainerGroupName startswith '$execution')."
}
exit 0
