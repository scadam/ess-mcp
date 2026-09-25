param([Parameter(Mandatory)][ValidateSet('servicenow', 'salesforce')][string] $System,
      [ValidateSet('setup', 'demo')][string] $Mode = 'setup')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# One-off provisioning jobs from the MCP image: SaaS credentials and the webhook key arrive as Key Vault references.
$rg = 'essmcp-caldova-rg'
$job = "job-desk-$System"
$image = (Get-Content .tmp\last-mcp-image.txt -Raw).Trim()
if ($image -notmatch '^cressmcpcaldovaf61b\.azurecr\.io/ess-mcp@sha256:[0-9a-f]{64}$') { throw 'Immutable image reference required.' }
$source = az containerapp show -g $rg -n "essmcp-caldova-$System" -o json | ConvertFrom-Json
$identity = @($source.identity.userAssignedIdentities.PSObject.Properties.Name)[0]
$secrets = @($source.properties.configuration.secrets | ForEach-Object { @{ name = $_.name; keyVaultUrl = $_.keyVaultUrl; identity = $identity } })
$secrets += @{ name = 'webhook-secret'; keyVaultUrl = "https://kv-essmcp-caldova-f61b.vault.azure.net/secrets/autopilot-webhook-$System"; identity = $identity }
$env = @($source.properties.template.containers[0].env | ForEach-Object {
  if ($_.secretRef) { @{ name = $_.name; secretRef = $_.secretRef } } else { @{ name = $_.name; value = $_.value } } })
$env += @{ name = 'AUTOPILOT_HOST_URL'; value = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io' }
$env += @{ name = 'AUTOPILOT_WEBHOOK_SECRET'; secretRef = 'webhook-secret' }
$definition = @{
  location = 'eastus2'
  identity = @{ type = 'UserAssigned'; userAssignedIdentities = @{ $identity = @{} } }
  properties = @{
    environmentId = $source.properties.environmentId
    workloadProfileName = 'Consumption'
    configuration = @{
      triggerType = 'Manual'; replicaTimeout = 1800; replicaRetryLimit = 0
      manualTriggerConfig = @{ parallelism = 1; replicaCompletionCount = 1 }
      secrets = $secrets
      registries = @(@{ server = 'cressmcpcaldovaf61b.azurecr.io'; identity = $identity })
    }
    template = @{ containers = @(@{
      name = 'provision'; image = $image
      command = @('python', '-m', "mcp_servers.provisioning.$System"); args = @($Mode)
      env = $env; resources = @{ cpu = 0.5; memory = '1Gi' }
    }) }
  }
}
$file = Join-Path $env:TEMP "$job.yaml"
$definition | ConvertTo-Json -Depth 12 | Set-Content -Path $file -Encoding utf8
$exists = az containerapp job show -g $rg -n $job --query name -o tsv 2>$null
if ($exists) { az containerapp job update -g $rg -n $job --yaml $file -o none } else { az containerapp job create -g $rg -n $job --yaml $file -o none }
"$job definition exit=$LASTEXITCODE"
Remove-Item $file -Force
$execution = az containerapp job start -g $rg -n $job --query name -o tsv
"execution=$execution"
foreach ($i in 1..60) {
  Start-Sleep -Seconds 10
  $status = az containerapp job execution show -g $rg -n $job --job-execution-name $execution --query properties.status -o tsv
  if ($status -in 'Succeeded', 'Failed', 'Stopped', 'Degraded') { break }
}
"status=$status"
$execution | Set-Content -NoNewline ".tmp\last-$job.txt"
exit 0
