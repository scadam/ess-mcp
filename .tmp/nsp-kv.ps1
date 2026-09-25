$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Same association the host Bicep declares; applied now so Key Vault references resolve for the provisioning jobs.
$rg = '/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg'
$nsp = "$rg/providers/Microsoft.Network/networkSecurityPerimeters/nsp-autopilot-caldova-78f0"
$body = @{ properties = @{ accessMode = 'Enforced'
  privateLinkResource = @{ id = "$rg/providers/Microsoft.KeyVault/vaults/kv-essmcp-caldova-f61b" }
  profile = @{ id = "$nsp/profiles/autopilot-state" } } } | ConvertTo-Json -Depth 5 -Compress
$file = Join-Path $env:TEMP 'nsp-kv.json'
Set-Content -Path $file -Value $body -NoNewline -Encoding utf8
az rest --method put --url "https://management.azure.com$nsp/resourceAssociations/essmcp-key-vault" --url-parameters 'api-version=2024-07-01' --body "@$file" --query "{state:properties.provisioningState,mode:properties.accessMode}" -o json
"put exit=$LASTEXITCODE"
Remove-Item $file -Force
foreach ($i in 1..18) {
  $state = az rest --method get --url "https://management.azure.com$nsp/resourceAssociations/essmcp-key-vault" --url-parameters 'api-version=2024-07-01' --query properties.provisioningState -o tsv
  if ($state -ne 'Accepted' -and $state -ne 'Updating' -and $state -ne 'Creating') { break }
  Start-Sleep -Seconds 10
}
"association state=$state"
exit 0
