param([string] $Image = '')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$root = 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp'
$session = Join-Path $root '.copilot-azure\sessions\78f002fe-15a9-4ba1-a633-f366fd8558a4'
if (-not $Image) { $Image = (Get-Content (Join-Path $session 'last-image.txt') -Raw).Trim() }
if ($Image -notmatch '^cressmcpcaldovaf61b\.azurecr\.io/autopilot@sha256:[0-9a-f]{64}$') { throw 'Immutable image reference required.' }
$env:AUTOPILOT_IMAGE = $Image
$bindingFile = Join-Path $session 'compliance-binding.json'
$env:AUTOPILOT_COMPLIANCE_BINDINGS = if (Test-Path $bindingFile) { (Get-Content $bindingFile -Raw | ConvertFrom-Json).bindings } else { '' }
"bindings: $(if ($env:AUTOPILOT_COMPLIANCE_BINDINGS) { 'from compliance-binding.json' } else { 'none' })"
$infra = Join-Path $root 'infra\autopilot-caldova'
$name = 'autopilot-caldova-app-' + (Get-Date -Format 'MMddHHmm')
"deploying $name with $Image"
$state = az deployment group create -g essmcp-caldova-rg -n $name -f (Join-Path $infra 'main.bicep') -p (Join-Path $infra 'app.bicepparam') --query properties.provisioningState -o tsv
"state=$state exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0 -or $state -ne 'Succeeded') { throw "Deployment $name did not succeed." }
$app = az containerapp show -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "{rev:properties.latestRevisionName, ready:properties.latestReadyRevisionName, running:properties.runningStatus}" -o json | ConvertFrom-Json
"revision=$($app.rev) ready=$($app.ready) running=$($app.running)"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
foreach ($i in 1..30) {
  try { if ((Invoke-WebRequest "$base/healthz" -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200) { 'healthz=200'; break } } catch {}
  Start-Sleep -Seconds 10
}
