$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Teams and Exchange service plans per demo person (group review chats and private chats need Teams).
$names = 'CharlotteW','AadiK','CassandraD','IsaacF','KrystalK','KadjiB','KenvinS','ElviaA','ColinB','KarinB','AishaW','KianL','DaisyP'
foreach ($n in $names) {
  $upn = "$n@caldova74201480.onmicrosoft.com"
  $d = az rest --method get --url "https://graph.microsoft.com/v1.0/users/$upn/licenseDetails" -o json 2>$null | ConvertFrom-Json
  $plans = @($d.value | ForEach-Object { $_.servicePlans } | Where-Object { $_.servicePlanName -match '^(TEAMS1|TEAMS_AR_DOD|EXCHANGE_S_(STANDARD|ENTERPRISE))$' -and $_.provisioningStatus -eq 'Success' } | ForEach-Object { $_.servicePlanName } | Sort-Object -Unique)
  $skus = @($d.value | ForEach-Object { $_.skuPartNumber }) -join ','
  "{0,-11} teams={1,-5} mail={2,-5} skus={3}" -f $n, [bool]($plans -contains 'TEAMS1'), [bool]($plans -match 'EXCHANGE'), $skus
}
exit 0
