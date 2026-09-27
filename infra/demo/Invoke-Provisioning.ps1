[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('servicenow', 'salesforce')][string] $System,
  [Parameter(Mandatory)][ValidateSet('setup', 'demo', 'reset')][string] $Mode,
  # ServiceNow demo incidents to raise or close; default both.
  [ValidateSet('battery', 'lockout', 'crash')][string[]] $Scenario = @()
)
# Runs one provisioning mode as a Container Apps job from the MCP server's own image. Credentials, the webhook key
# and the demo sign-in password reach the job only as Key Vault references.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription

$source = Get-DemoApp "essmcp-caldova-$System"
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
      command = @('python', '-u', '-m', "mcp_servers.provisioning.$System"); args = @(@($Mode) + $Scenario)
      env = $variables; resources = @{ cpu = 0.5; memory = '1Gi' }
    }) }
  }
}
Start-DemoJob -Job "job-desk-$System" -Definition $definition -Label "$System $Mode $($Scenario -join ' ')".Trim() | Out-Null
exit 0
