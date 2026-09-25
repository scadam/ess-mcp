$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $body = @{ scenario = 'compliance-case-resolution'; prompt = 'compliance case resolution' } | ConvertTo-Json
  $r = Invoke-WebRequest "$base/api/agentic-instances/a6a9c9be-e1ee-4abc-b661-c8f906dd79b4/run" -Method Post -Headers $h -ContentType 'application/json' -Body $body -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 60
  "run -> $($r.StatusCode) $($r.Content)"
  Start-Sleep -Seconds 45
  $feed = Invoke-RestMethod "$base/api/control-room/activity?instance=a6a9c9be-e1ee-4abc-b661-c8f906dd79b4&limit=40" -Headers $h -TimeoutSec 60
  @($feed.events) | Sort-Object at | ForEach-Object {
    $when = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$_.at).ToLocalTime().ToString('HH:mm:ss')
    "{0} {1,-11} {2,-7} {3}" -f $when, $_.category, $_.status, ($_.title.Substring(0, [Math]::Min(110, $_.title.Length)))
  }
} finally { $tok = $null; $h = $null }
