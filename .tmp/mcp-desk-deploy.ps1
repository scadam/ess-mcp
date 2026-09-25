param([string] $Image = '')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$rg = 'essmcp-caldova-rg'
if ((az account show --query id -o tsv) -ne '54b04cf7-73f7-4ea0-aa82-b15694ea8033') { throw 'Wrong subscription.' }
if (-not $Image) {
  $ctx = (& .\.venv\Scripts\python.exe infra\caldova\deployment_support.py stage | Select-Object -Last 1).Trim()
  if (-not (Test-Path (Join-Path $ctx 'Dockerfile'))) { throw "Staging failed: $ctx" }
  $tag = 'desk-' + (Get-Date -Format 'MMddHHmm')
  az acr build --registry cressmcpcaldovaf61b --image "ess-mcp:$tag" --file (Join-Path $ctx 'Dockerfile') $ctx --no-logs -o none
  if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
  Remove-Item -Recurse -Force $ctx
  $digest = az acr repository show -n cressmcpcaldovaf61b --image "ess-mcp:$tag" --query digest -o tsv
  $Image = "cressmcpcaldovaf61b.azurecr.io/ess-mcp@$digest"
}
if ($Image -notmatch '^cressmcpcaldovaf61b\.azurecr\.io/ess-mcp@sha256:[0-9a-f]{64}$') { throw 'Immutable image reference required.' }
"image=$Image"
$Image | Set-Content -NoNewline .tmp\last-mcp-image.txt
$caller = @(
  'AUTOPILOT_CALLER_TENANT_ID=17371818-07cb-47f2-9ca3-18f96f0125d7',
  'AUTOPILOT_CALLER_AUDIENCE=api://a11a4108-2a76-471a-912b-8db27c91879c,a11a4108-2a76-471a-912b-8db27c91879c',
  'AUTOPILOT_CALLER_APP_IDS=23eca8da-8e67-49b9-815e-77c100429d0a'
)
foreach ($name in 'servicenow', 'salesforce', 'coupa') {
  $app = "essmcp-caldova-$name"
  if ($name -eq 'servicenow') { az containerapp update -n $app -g $rg --image $Image --set-env-vars @caller -o none }
  else { az containerapp update -n $app -g $rg --image $Image -o none }
  "$name update exit=$LASTEXITCODE"
}
foreach ($name in 'servicenow', 'salesforce', 'coupa') {
  az containerapp show -n "essmcp-caldova-$name" -g $rg --query "{app:name,ready:properties.latestReadyRevisionName,latest:properties.latestRevisionName,running:properties.runningStatus}" -o json | ConvertFrom-Json | ForEach-Object { "$($_.app) latest=$($_.latest) ready=$($_.ready) running=$($_.running)" }
}
exit 0
