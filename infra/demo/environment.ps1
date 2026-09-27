# Shared names and helpers for the demo operations scripts in this folder (dot-source it).
$DemoTenant = '17371818-07cb-47f2-9ca3-18f96f0125d7'
$DemoSubscription = '54b04cf7-73f7-4ea0-aa82-b15694ea8033'
$DemoResourceGroup = 'essmcp-caldova-rg'
$DemoVault = 'kv-essmcp-caldova-f61b'
$DemoRegistry = 'cressmcpcaldovaf61b.azurecr.io'
$DemoHostUrl = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$DemoControlPlaneScope = 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user'
$env:AZURE_CONFIG_DIR = Join-Path $env:LOCALAPPDATA 'ess-mcp\azure-caldova74201480'

function Assert-DemoSubscription {
  $account = az account show --query '{id:id, tenant:tenantId}' -o json 2>$null | ConvertFrom-Json
  if (-not $account) { throw "Sign in first: `$env:AZURE_CONFIG_DIR='$env:AZURE_CONFIG_DIR'; az login --tenant $DemoTenant" }
  if ($account.id -ne $DemoSubscription -or $account.tenant -ne $DemoTenant) {
    throw "The Azure CLI profile in $env:AZURE_CONFIG_DIR is not on the demo subscription $DemoSubscription."
  }
}

function Get-DemoOperatorToken {
  $token = az account get-access-token --scope $DemoControlPlaneScope --query accessToken -o tsv
  if (-not $token) { throw 'Could not get a control-plane token for the signed-in operator.' }
  $token
}

function Invoke-DemoArm {
  # Direct Resource Manager calls: the containerapp CLI extension can stall silently on job commands.
  param([string] $Method = 'Get', [Parameter(Mandatory)][string] $Path, $Body)
  if (-not $script:DemoArmToken -or ((Get-Date) - $script:DemoArmTokenAt).TotalMinutes -gt 30) {
    $script:DemoArmToken = az account get-access-token --resource 'https://management.azure.com/' --query accessToken -o tsv
    $script:DemoArmTokenAt = Get-Date
  }
  $request = @{ Method = $Method; Uri = "https://management.azure.com$Path"; TimeoutSec = 120
                Headers = @{ Authorization = "Bearer $script:DemoArmToken" } }
  if ($null -ne $Body) { $request.ContentType = 'application/json'; $request.Body = $Body | ConvertTo-Json -Depth 20 -Compress }
  Invoke-RestMethod @request
}

function Get-DemoAppPath([string] $App) {
  "/subscriptions/$DemoSubscription/resourceGroups/$DemoResourceGroup/providers/Microsoft.App/containerApps/$($App)?api-version=2024-03-01"
}

function Get-DemoApp([string] $App) { Invoke-DemoArm -Path (Get-DemoAppPath $App) }

function Get-DemoVaultSecretPath([string] $Name) {
  "/subscriptions/$DemoSubscription/resourceGroups/$DemoResourceGroup/providers/Microsoft.KeyVault/vaults/$DemoVault/" +
  "secrets/$($Name)?api-version=2023-07-01"
}

function Set-DemoVaultSecret {
  # Through Azure Resource Manager: the vault's data plane is closed to public networks.
  param([Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]+$')][string] $Name, [Parameter(Mandatory)][string] $Value)
  Invoke-DemoArm -Method Put -Path (Get-DemoVaultSecretPath $Name) -Body @{ properties = @{ value = $Value } } | Out-Null
}

function Test-DemoVaultSecret([string] $Name) {
  try {
    Invoke-DemoArm -Path (Get-DemoVaultSecretPath $Name) | Out-Null
    $true
  } catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) { $false } else { throw }
  }
}

function Wait-DemoApp {
  # Waits until the app's newest revision is the ready one and its /healthz answers.
  param([Parameter(Mandatory)][string] $App, [int] $TimeoutSeconds = 600)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $state = Get-DemoApp $App
    $fqdn = $state.properties.configuration.ingress.fqdn
    if ($state.properties.latestReadyRevisionName -eq $state.properties.latestRevisionName) {
      try {
        if ((Invoke-WebRequest "https://$fqdn/healthz" -UseBasicParsing -TimeoutSec 20).StatusCode -eq 200) {
          return $state.properties.latestReadyRevisionName
        }
      } catch { }
    }
    Start-Sleep -Seconds 10
  }
  throw "$App did not become healthy within $TimeoutSeconds seconds."
}

function Start-DemoJob {
  # Creates or updates a manual Container Apps job from a definition, starts it and waits for the execution.
  param([Parameter(Mandatory)][string] $Job, [Parameter(Mandatory)][hashtable] $Definition, [string] $Label = $Job,
        [int] $TimeoutMinutes = 20)
  $path = "/subscriptions/$DemoSubscription/resourceGroups/$DemoResourceGroup/providers/Microsoft.App/jobs/$Job"
  Invoke-DemoArm -Method Put -Path "$($path)?api-version=2024-03-01" -Body $Definition | Out-Null
  foreach ($i in 1..60) {
    $state = (Invoke-DemoArm -Path "$($path)?api-version=2024-03-01").properties.provisioningState
    if ($state -eq 'Succeeded') { break }
    if ($state -in 'Failed', 'Canceled') { throw "The $Job job definition ended $state." }
    Start-Sleep -Seconds 5
  }
  $execution = (Invoke-DemoArm -Method Post -Path "$path/start?api-version=2024-03-01" -Body @{}).name
  if (-not $execution) { throw "The $Job job did not start." }
  Write-Host "$Label -> $execution" -NoNewline
  $status = ''
  $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    $status = (Invoke-DemoArm -Path "$path/executions/$($execution)?api-version=2024-03-01").properties.status
    if ($status -in 'Succeeded', 'Failed', 'Stopped', 'Degraded') { break }
    Write-Host '.' -NoNewline
  }
  Write-Host " $status"
  if ($status -ne 'Succeeded') {
    throw "$Job execution $execution ended '$status'. Its log is in Log Analytics (ContainerAppConsoleLogs, ContainerGroupName startswith '$execution')."
  }
  $execution
}

function New-DemoSecret([int] $Length = 40) {
  $alphabet = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  -join (1..$Length | ForEach-Object { $alphabet[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($alphabet.Length)] })
}
