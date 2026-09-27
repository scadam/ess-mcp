$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
. .\infra\demo\environment.ps1
$env:PYTHONIOENCODING = 'utf-8'
Assert-DemoSubscription
# Build the MCP image from a secret-free staged context, then roll it to the three desk MCP apps through ARM.
$ctx = (& .\.venv\Scripts\python.exe infra\caldova\deployment_support.py stage | Select-Object -Last 1).Trim()
if (-not (Test-Path (Join-Path $ctx 'Dockerfile'))) { throw "Staging failed: $ctx" }
$tag = 'desk-' + (Get-Date -Format 'MMddHHmm')
az acr build --registry cressmcpcaldovaf61b --image "ess-mcp:$tag" --file (Join-Path $ctx 'Dockerfile') $ctx --no-logs -o none
if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }
Remove-Item -Recurse -Force $ctx
$digest = az acr repository show -n cressmcpcaldovaf61b --image "ess-mcp:$tag" --query digest -o tsv
$image = "$DemoRegistry/ess-mcp@$digest"
"image=$image"
$image | Set-Content -NoNewline .tmp\last-mcp-image.txt
foreach ($name in 'servicenow', 'salesforce', 'coupa') {
  $app = "essmcp-caldova-$name"
  $template = (Get-DemoApp $app).properties.template
  $template.containers[0].image = $image
  $template.revisionSuffix = 'img' + (Get-Date -Format 'MMddHHmmss')
  Invoke-DemoArm -Method Patch -Path (Get-DemoAppPath $app) -Body @{ properties = @{ template = $template } } | Out-Null
  "$app patched"
}
Start-Sleep -Seconds 20
foreach ($name in 'servicenow', 'salesforce', 'coupa') { "essmcp-caldova-$name ready: $(Wait-DemoApp "essmcp-caldova-$name")" }
exit 0
