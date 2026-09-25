param([int] $Take = 12)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Desk overview plus each open case's latest timeline entries.
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $token" }
$desk = Invoke-RestMethod "$base/api/case-desk" -Headers $h
"counts: $($desk.counts | ConvertTo-Json -Compress)  watermarks: $(($desk.watermarks.PSObject.Properties.Name) -join ',')"
foreach ($row in @($desk.cases)) {
  $case = Invoke-RestMethod "$base/api/case-desk/cases/$($row.key)" -Headers $h
  ""
  "== [$($row.function)] $($row.number) $($row.title.Substring(0, [Math]::Min(80, $row.title.Length)))"
  "   status=$($case.status) waiting=$(($case.waiting | ConvertTo-Json -Compress)) turns=$($case.turns) tokens=$($case.tokens) errors=$($case.errors) requester=$($case.requester.name) <$($case.requester.email)> review=$([bool]$case.review)"
  foreach ($entry in @($case.timeline | Select-Object -Last $Take)) {
    $when = [DateTimeOffset]::FromUnixTimeSeconds([long]$entry.at).UtcDateTime.ToString('HH:mm:ss')
    $text = ($entry.text -replace '\s+', ' ')
    "   $when $($entry.kind) [$($entry.who)] $($text.Substring(0, [Math]::Min(260, $text.Length)))"
  }
}
$token = $null
exit 0
