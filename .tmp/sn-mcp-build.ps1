$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$sub = az account show --query id -o tsv
if ($sub -ne '54b04cf7-73f7-4ea0-aa82-b15694ea8033') { throw "Wrong subscription: $sub" }
$current = az containerapp show -n essmcp-caldova-servicenow -g essmcp-caldova-rg --query "properties.template.containers[0].image" -o tsv
"current=$current"
$ctx = (& .\.venv\Scripts\python.exe infra\caldova\deployment_support.py stage | Select-Object -Last 1).Trim()
if (-not (Test-Path (Join-Path $ctx 'Dockerfile'))) { throw "Staging failed: $ctx" }
"context=$ctx"
$tag = 'sncatalog-' + (Get-Date -Format 'MMddHHmm')
az acr build --registry cressmcpcaldovaf61b --image "ess-mcp:$tag" --file (Join-Path $ctx 'Dockerfile') $ctx --no-logs -o none
"build exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { exit 1 }
$digest = az acr repository show -n cressmcpcaldovaf61b --image "ess-mcp:$tag" --query digest -o tsv
"tag=$tag"
"digest=$digest"
Remove-Item -Recurse -Force $ctx
exit 0
