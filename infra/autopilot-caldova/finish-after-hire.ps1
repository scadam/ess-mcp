[CmdletBinding()]
param(
  [string] $InstanceName = 'Compliance Agent',
  [string[]] $RequesterUpns = @('admin@caldova74201480.onmicrosoft.com', 'WondaH@Caldova74201480.OnMicrosoft.com'),
  [string] $Image = ''
)
# After the instance is hired: bind it (verified directory lookups + evidence paths),
# redeploy the host through Bicep with that binding, and wait for health.
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$session = Join-Path $root '.copilot-azure/sessions/78f002fe-15a9-4ba1-a633-f366fd8558a4'
if (-not $Image) { $Image = (Get-Content (Join-Path $session 'last-image.txt') -Raw).Trim() }
if ($Image -notmatch '^cressmcpcaldovaf61b\.azurecr\.io/autopilot@sha256:[0-9a-f]{64}$') { throw 'A verified immutable image reference is required.' }

$result = & (Join-Path $PSScriptRoot 'configure-compliance-binding.ps1') -InstanceName $InstanceName `
  -RequesterUpns $RequesterUpns -EvidenceFile (Join-Path $session 'evidence-library.json') -SetManagerIfMissing | ConvertFrom-Json
Set-Content (Join-Path $session 'compliance-binding.json') -Value ($result | ConvertTo-Json -Depth 5) -Encoding utf8NoBOM
"Bound instance $($result.instanceObjectId) / agentic user $($result.agenticUserUpn) / manager $($result.manager)"

$env:AUTOPILOT_IMAGE = $Image
$env:AUTOPILOT_COMPLIANCE_BINDINGS = $result.bindings
$name = 'autopilot-caldova-app-' + (Get-Date -Format 'MMddHHmm')
$state = az deployment group create -g essmcp-caldova-rg -n $name -f (Join-Path $PSScriptRoot 'main.bicep') `
  -p (Join-Path $PSScriptRoot 'app.bicepparam') --query properties.provisioningState -o tsv
if ($LASTEXITCODE -ne 0 -or $state -ne 'Succeeded') { throw "Deployment $name did not succeed." }

$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
foreach ($i in 1..30) {
  try { if ((Invoke-WebRequest "$base/healthz" -UseBasicParsing -TimeoutSec 15).StatusCode -eq 200) { 'Host healthy with the compliance binding.'; exit 0 } } catch {}
  Start-Sleep -Seconds 10
}
throw 'The host did not report healthy after the binding deployment.'
