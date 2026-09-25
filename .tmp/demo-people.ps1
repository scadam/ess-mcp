$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Which demo role holders and requesters exist as licensed, enabled Entra users (reviews and Teams chats need them).
$names = 'CharlotteW','AadiK','CassandraD','KianL','IsaacF','KatriA','KatL','KrystalK','KadjiB','KenvinS','ElviaA','ColinB','KarinB','AishaW','DaisyP','KimR','DavidS'
foreach ($n in $names) {
  $upn = "$n@caldova74201480.onmicrosoft.com"
  $u = az rest --method get --url "https://graph.microsoft.com/v1.0/users/$upn" --url-parameters '$select=displayName,accountEnabled,jobTitle,department,usageLocation,assignedLicenses' -o json 2>$null | ConvertFrom-Json
  if ($u) { "{0,-12} {1,-20} enabled={2} licenses={3} title={4} | {5}" -f $n, $u.displayName, $u.accountEnabled, @($u.assignedLicenses).Count, $u.jobTitle, $u.department }
  else { "{0,-12} (not found)" -f $n }
}
exit 0
