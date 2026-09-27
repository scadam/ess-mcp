$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user --query accessToken -o tsv
$feed = Invoke-RestMethod "$base/api/control-room/activity?limit=500" -Headers @{ Authorization = "Bearer $token" }
"events: $($feed.events.Count) (revision $($feed.revision))"
$feed.events | Where-Object { $_.category -in 'notification', 'lifecycle', 'email' -or $_.title -match '(?i)comment|word|document|mention' } |
  Select-Object -First 40 | ForEach-Object {
    '{0} | {1} | {2} | {3} | {4}' -f ([DateTimeOffset]::FromUnixTimeMilliseconds([int64]$_.at).ToString('MM-dd HH:mm')), $_.instance.Substring(0, [Math]::Min(8, $_.instance.Length)), $_.category, $_.title, ("$($_.detail)" -replace '\s+', ' ').Substring(0, [Math]::Min(140, "$($_.detail)".Length))
  }
exit 0
