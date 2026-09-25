param([string[]] $Sources = @('servicenow', 'salesforce'))
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Creates webhook signing secrets through the ARM control plane (the vault's data plane is private); values are never printed.
$vault = '/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg/providers/Microsoft.KeyVault/vaults/kv-essmcp-caldova-f61b'
$alphabet = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
foreach ($source in $Sources) {
  $name = "autopilot-webhook-$source"
  $url = "https://management.azure.com$vault/secrets/$name"
  $existing = az rest --method get --url $url --url-parameters 'api-version=2023-07-01' --query name -o tsv 2>$null
  if ($LASTEXITCODE -eq 0 -and $existing -eq $name) { "$name exists; not rotated"; continue }
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $value = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
  $file = Join-Path $env:TEMP ("kvbody-" + [guid]::NewGuid().ToString('N') + '.json')
  try {
    @{ properties = @{ value = $value; contentType = "HMAC-SHA256 key for $source webhooks" } } | ConvertTo-Json -Compress | Set-Content -Path $file -NoNewline -Encoding utf8
    az rest --method put --url $url --url-parameters 'api-version=2023-07-01' --body "@$file" --query name -o tsv | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Creating $name failed." }
    "$name created (48 chars)"
  } finally {
    Remove-Item -Force $file -ErrorAction SilentlyContinue
    $value = $null
  }
}
exit 0
