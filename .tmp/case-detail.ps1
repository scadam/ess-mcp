param([Parameter(Mandatory)][string[]] $Keys)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$desk = Invoke-RestMethod "$base/api/case-desk" -Headers @{ Authorization = "Bearer $token" }
foreach ($prefix in $Keys) {
  $key = ($desk.cases | Where-Object { $_.key.StartsWith($prefix) } | Select-Object -First 1).key
  if (-not $key) { "no case $prefix"; continue }
  $c = Invoke-RestMethod "$base/api/case-desk/cases/$key" -Headers @{ Authorization = "Bearer $token" }
  "=== $($c.record.number) | $($c.status) | $($c.title)"
  "requester: $($c.requester | ConvertTo-Json -Compress)"
  "waiting: $($c.waiting | ConvertTo-Json -Compress)"
  foreach ($t in @($c.timeline)) {
    $when = [DateTimeOffset]::FromUnixTimeSeconds([long]$t.at).UtcDateTime.ToString('MM-dd HH:mm')
    $text = [string]$t.text
    if ($text.Length -gt 700) { $text = $text.Substring(0, 700) + '…' }
    "  $when [$($t.kind)] $($t.by): $text"
  }
}
$token = $null
exit 0
