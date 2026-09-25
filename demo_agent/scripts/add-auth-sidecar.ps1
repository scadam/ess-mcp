# Adds the official Entra auth-sidecar as a second container to the
# `ess-demo-agent` Container App, configures the main container to acquire
# Agent-Identity-scoped tokens through it, and rolls a new revision.
#
# Pre-requisites:
#  - Logged into az.cmd against the right subscription/tenant.
#  - The Blueprint app (3f028e66-...) already has a federated credential
#    accepting the system-assigned MI of `ess-demo-agent` as subject.
#
# Usage: pwsh -File demo_agent/scripts/add-auth-sidecar.ps1
[CmdletBinding()]
param(
  [string]$ResourceGroup    = 'essmcp-rg',
  [string]$ContainerApp     = 'ess-demo-agent',
  [string]$RevisionSuffix   = "sidecar1",
  [string]$TenantId         = '8030d928-e557-4a4c-ae1e-95c1c4125eaa',
  [string]$BlueprintAppId   = '3f028e66-44cf-4cee-81ee-03ade7717884',
  [string]$AgentAppId       = 'ed4046aa-a3ef-4685-a73d-ecda5a4f01da',
  [string]$A365ResourceAppId = '9b975845-388f-4429-889e-eab1ef63949c',
  [string]$SidecarImage     = 'mcr.microsoft.com/entra-sdk/auth-sidecar:1.0.0-azurelinux3.0-distroless'
)

$ErrorActionPreference = 'Stop'

$tmpFull = Join-Path ([System.IO.Path]::GetTempPath()) "$ContainerApp-full.json"
az.cmd containerapp show -n $ContainerApp -g $ResourceGroup -o json | Out-File -FilePath $tmpFull -Encoding utf8
$app = Get-Content $tmpFull -Raw | ConvertFrom-Json -Depth 100

function Set-EnvVar($list, $name, $value) {
  $existing = $list | Where-Object { $_.name -eq $name }
  if ($existing) {
    $existing.value = $value
    if ($existing.PSObject.Properties.Name -contains 'secretRef') {
      $existing.PSObject.Properties.Remove('secretRef')
    }
  } else {
    [void]$list.Add([pscustomobject]@{ name = $name; value = $value })
  }
}

# Main container: switch to sidecar token source
$mainEnv = [System.Collections.ArrayList]@($app.properties.template.containers[0].env)
Set-EnvVar $mainEnv 'A365_OBSERVABILITY_TOKEN_SOURCE' 'agent_identity_sidecar'
Set-EnvVar $mainEnv 'A365_SIDECAR_URL'                'http://localhost:5000'
Set-EnvVar $mainEnv 'A365_SIDECAR_DOWNSTREAM_API'     'a365'
Set-EnvVar $mainEnv 'A365_AGENT_APP_ID'               $AgentAppId
# Also expose the sidecar's Graph endpoint so HITL 1:1 chat delivery can mint
# a Graph token AS the agent identity (not as the blueprint app), avoiding the
# app-only 401 from POST /chats/{id}/messages.
Set-EnvVar $mainEnv 'A365_SIDECAR_GRAPH_API'          'graph'
$app.properties.template.containers[0].env = $mainEnv.ToArray()

# Sidecar container
$sidecarEnv = @(
  [pscustomobject]@{ name = 'ASPNETCORE_URLS';                              value = 'http://+:5000' },
  [pscustomobject]@{ name = 'AzureAd__Instance';                            value = 'https://login.microsoftonline.com/' },
  [pscustomobject]@{ name = 'AzureAd__TenantId';                            value = $TenantId },
  [pscustomobject]@{ name = 'AzureAd__ClientId';                            value = $BlueprintAppId },
  [pscustomobject]@{ name = 'AzureAd__ClientCredentials__0__SourceType';    value = 'SignedAssertionFromManagedIdentity' },
  [pscustomobject]@{ name = 'DownstreamApis__a365__BaseUrl';                value = 'https://agent365.svc.cloud.microsoft' },
  [pscustomobject]@{ name = 'DownstreamApis__a365__Scopes__0';              value = "api://$A365ResourceAppId/.default" },
  [pscustomobject]@{ name = 'DownstreamApis__a365__RequestAppToken';        value = 'true' },
  # Current Work IQ requires delegated-user context. This configuration does
  # not grant app-only access and must not be used as an authorization fallback.
  [pscustomobject]@{ name = 'DownstreamApis__workiq__BaseUrl';             value = 'https://workiq.svc.cloud.microsoft' },
  [pscustomobject]@{ name = 'DownstreamApis__workiq__Scopes__0';           value = 'api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask' },
  [pscustomobject]@{ name = 'DownstreamApis__workiq__RequestAppToken';     value = 'false' },
  # Microsoft Graph downstream — used by graph_chat for agent-identity 1:1
  # Teams chat HITL delivery. The AgentIdentity query parameter sent by the
  # caller selects which agent identity the sidecar mints the token for.
  [pscustomobject]@{ name = 'DownstreamApis__graph__BaseUrl';               value = 'https://graph.microsoft.com' },
  [pscustomobject]@{ name = 'DownstreamApis__graph__Scopes__0';             value = 'https://graph.microsoft.com/.default' },
  [pscustomobject]@{ name = 'DownstreamApis__graph__RequestAppToken';       value = 'true' },
  [pscustomobject]@{ name = 'Logging__LogLevel__Default';                   value = 'Information' }
)
$sidecar = [pscustomobject]@{
  name      = 'auth-sidecar'
  image     = $SidecarImage
  resources = [pscustomobject]@{ cpu = 0.25; memory = '0.5Gi' }
  env       = $sidecarEnv
}

$existingContainers = $app.properties.template.containers | Where-Object { $_.name -ne 'auth-sidecar' }
$app.properties.template.containers = @($existingContainers) + @($sidecar)
$app.properties.template.revisionSuffix = $RevisionSuffix

$outPath = Join-Path ([System.IO.Path]::GetTempPath()) "$ContainerApp-with-sidecar.json"
$app | ConvertTo-Json -Depth 100 | Out-File -FilePath $outPath -Encoding utf8
Write-Host "Wrote: $outPath"
Write-Host ("Containers: " + (($app.properties.template.containers | ForEach-Object { $_.name }) -join ', '))

Write-Host "==> Applying with az containerapp update --yaml ..."
az.cmd containerapp update -n $ContainerApp -g $ResourceGroup --yaml $outPath
