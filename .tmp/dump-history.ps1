param([int] $Limit = 120)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $feed = Invoke-RestMethod "$base/api/control-room/activity?instance=a6a9c9be-e1ee-4abc-b661-c8f906dd79b4&limit=$Limit" -Headers $h -TimeoutSec 60
  $lines = @($feed.events) | Sort-Object at | ForEach-Object {
    $when = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$_.at).ToLocalTime().ToString('HH:mm:ss')
    $detail = ([string]$_.detail -replace '\s+', ' ')
    $result = ([string]$_.result -replace '\s+', ' ')
    "{0} {1,-11} {2,-7} {3}" -f $when, $_.category, $_.status, $_.title
    if ($_.category -in 'teams-in', 'teams-out', 'email', 'issue', 'case', 'notification' -and $detail) { "           detail: " + $detail.Substring(0, [Math]::Min(700, $detail.Length)) }
    if ($_.category -eq 'issue' -and $result) { "           result: " + $result.Substring(0, [Math]::Min(300, $result.Length)) }
  }
  $lines | Out-File "$env:TEMP\ap-feed.txt" -Encoding utf8
  $cases = Invoke-RestMethod "$base/api/compliance/cases" -Headers $h -TimeoutSec 60
  $cases | ConvertTo-Json -Depth 8 | Out-File "$env:TEMP\ap-cases.json" -Encoding utf8
  "feed lines: $(@($lines).Count); cases: $(@($cases.cases).Count)"
} finally { $tok = $null; $h = $null }
