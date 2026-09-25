$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
try {
  $anon = try { (Invoke-WebRequest "$base/api/control-room" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { [int]$_.Exception.Response.StatusCode }
  "anonymous /api/control-room -> $anon"
  $room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 30
  "control-room keys: " + (($room.PSObject.Properties.Name) -join ', ')
  $tiles = @($room.colleagues) + @($room.tiles) + @($room.instances) | Where-Object { $_ }
  $tiles | Select-Object -First 5 | ForEach-Object { "  tile: {0} | {1} | {2}" -f $_.name, $_.state, $_.role }
  $act = Invoke-RestMethod "$base/api/control-room/activity" -Headers $h -TimeoutSec 30
  $items = @($act.items) + @($act.events) + @($act.activity) | Where-Object { $_ }
  "activity items: $(@($items).Count)"
  $items | Select-Object -First 4 | ForEach-Object { "  {0} {1} {2}" -f $_.at, $_.category, $_.title }
  $skills = Invoke-RestMethod "$base/api/skills" -Headers $h -TimeoutSec 30
  $s = @($skills) + @($skills.skills) | Where-Object { $_.id -eq 'compliance-case-resolution' -or $_.name -match 'Compliance' } | Select-Object -First 1
  "compliance skill: name=$($s.name) title=$($s.title) category=$($s.category) servers=$(@($s.servers) -join ',')"
  $servers = Invoke-RestMethod "$base/api/servers" -Headers $h -TimeoutSec 30
  (@($servers) + @($servers.servers) | Where-Object { $_.name }) | ForEach-Object { "  server: {0} connected={1} tools={2}" -f $_.name, $_.connected, $_.toolCount }
  $html = (Invoke-WebRequest "$base/control-plane" -UseBasicParsing -TimeoutSec 30).Content
  $css = (Invoke-WebRequest "$base/static/autopilot-theme.css" -UseBasicParsing -TimeoutSec 30).Content
  "page has controlRoomView=$($html.Contains('controlRoomView')) old-dark-console=$($html.Contains('cr-backdrop')) theme-follows=$($css.Contains('Control room follows the page theme'))"
} finally { $tok = $null; $h = $null }
