$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$models = az cognitiveservices account list-models -g essmcp-caldova-rg -n oai-autopilot-caldova-78f0 -o json | ConvertFrom-Json
$wanted = $models | Where-Object { $_.format -eq 'OpenAI' -and $_.name -match '^(gpt-4\.1|gpt-4o-mini|o3|o4-mini|o3-mini|gpt-5)' } |
  ForEach-Object { [pscustomobject]@{ name = $_.name; version = $_.version; skus = (@($_.skus | ForEach-Object { $_.name }) -join ',');
    lifecycle = $_.lifecycleStatus; deprecation = $_.deprecation.inference } } | Sort-Object name, version
$wanted | Format-Table -AutoSize | Out-String -Width 220
$usage = az cognitiveservices usage list -l eastus2 -o json | ConvertFrom-Json
$usage | Where-Object { $_.name.value -match 'GlobalStandard\.(gpt-4\.1|o4-mini|o3|gpt-5)' } |
  ForEach-Object { '{0} used={1} limit={2}' -f $_.name.value, $_.currentValue, $_.limit }
az cognitiveservices account deployment list -g essmcp-caldova-rg -n oai-autopilot-caldova-78f0 --query "[].{name:name, model:properties.model.name, version:properties.model.version, sku:sku.name, capacity:sku.capacity}" -o table
