param([string] $Name = 'HR Agent', [int] $Limit = 200)
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 60
  $tile = @($room.instances) | Where-Object { $_.name -eq $Name } | Select-Object -First 1
  foreach ($i in @($room.instances)) { "tile: {0} kind={1} key={2}" -f $i.name, $i.kind, $i.key }
  if (-not $tile) { throw "No tile named $Name." }
  $feed = Invoke-RestMethod "$base/api/control-room/activity?instance=$($tile.key)&limit=$Limit" -Headers $h -TimeoutSec 60
  $lines = @($feed.events) | Sort-Object at | ForEach-Object {
    $when = [DateTimeOffset]::FromUnixTimeMilliseconds([int64]$_.at).ToLocalTime().ToString('HH:mm:ss')
    $detail = ([string]$_.detail -replace '\s+', ' ')
    "{0} {1,-10} {2,-7} {3}" -f $when, $_.category, $_.status, $_.title
    if ($detail) { "           detail: " + $detail.Substring(0, [Math]::Min(900, $detail.Length)) }
  }
  $lines | Out-File "$env:TEMP\ap-hr-feed.txt" -Encoding utf8
  $runs = Invoke-RestMethod "$base/api/runs" -Headers $h -TimeoutSec 60
  @($runs) | Where-Object { $_.instanceKey -eq $tile.key } | ForEach-Object {
    [pscustomobject]@{ id = $_.id; title = $_.title; status = $_.status; prompt = $_.prompt; result = $_.result; approvalStatus = $_.approvalStatus; tools = @($_.toolCalls | ForEach-Object { "$($_.server).$($_.tool)" }) -join ',' }
  } | ConvertTo-Json -Depth 5 | Out-File "$env:TEMP\ap-hr-runs.json" -Encoding utf8
  "feed lines: $(@($lines).Count)"
} finally { $tok = $null; $h = $null }
