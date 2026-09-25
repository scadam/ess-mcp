# Additive infrastructure conformance: the greenfield checker assumes a new
# Key Vault and ACR and cannot validate existing-resource references.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$session = Join-Path $root '.copilot-azure/sessions/78f002fe-15a9-4ba1-a633-f366fd8558a4'
$plan = Get-Content (Join-Path $session 'prepare-plan.json') -Raw | ConvertFrom-Json
$main = Get-Content (Join-Path $PSScriptRoot 'main.bicep') -Raw
$guard = Get-Content (Join-Path $PSScriptRoot 'deployment-guard.bicep') -Raw
$docker = Get-Content (Join-Path $PSScriptRoot 'Dockerfile.autopilot') -Raw
$ignore = Get-Content (Join-Path $PSScriptRoot 'Dockerfile.autopilot.dockerignore') -Raw
$checks = @(
  @{ name='approved resource names'; ok=(@($plan.naming.resources | Where-Object { $main.Contains($_.name) }).Count -eq 4) }
  @{ name='scope guard'; ok=($guard.Contains($plan.a365Plan.tenantId) -and $guard.Contains('54b04cf7-73f7-4ea0-aa82-b15694ea8033') -and $guard.Contains('essmcp-caldova-rg')) }
  @{ name='reuse existing vault/ACR/environment'; ok=($main -match "Microsoft.KeyVault/vaults@[^']+' existing" -and $main -match "Microsoft.ContainerRegistry/registries@[^']+' existing" -and $main -match "Microsoft.App/managedEnvironments@[^']+' existing") }
  @{ name='private Entra-only storage'; ok=($main.Contains('allowSharedKeyAccess: false') -and $main.Contains("publicAccess: 'None'") -and $main.Contains('defaultToOAuthAuthentication: true')) }
  @{ name='runtime least privilege'; ok=($main.Contains('ba92f5b4-2d11-453d-a403-e96b0029c9fe') -and $main.Contains('7f951dda-4ed3-4680-a7ca-43fe172d538d') -and $main.Contains('5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') -and $main.Contains('scope: blueprintCredential')) }
  @{ name='app gated by identity and immutable image'; ok=($main.Contains('if (deployApp)') -and $main.Contains('@sha256:') -and $main.Contains('appConfigurationIsReady: any(appReady)')) }
  @{ name='no legacy messaging audience'; ok=($main.Contains('5a807f24-c9de-44ee-a3a7-329e88a00ffc/.default') -and -not $main.Contains('api.botframework.com')) }
  @{ name='credentialless build source'; ok=(-not $docker.Contains('COPY demo_agent ./demo_agent') -and $ignore.Contains('!demo_agent/*.py') -and -not $ignore.Contains('!demo_agent/.env')) }
  @{ name='old tenant absent'; ok=(-not $main.Contains('8030d928-e557-4a4c-ae1e-95c1c4125eaa') -and -not $main.Contains('3f028e66-44cf-4cee-81ee-03ade7717884')) }
)
$checks | ForEach-Object { [pscustomobject]@{ name=$_.name; passed=[bool]$_.ok } } | ConvertTo-Json
if (@($checks | Where-Object { -not $_.ok }).Count -gt 0) { exit 1 }
exit 0