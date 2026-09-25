$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
foreach ($i in 1..30) {
  $app = az containerapp show -g essmcp-caldova-rg -n ca-autopilot-caldova-78f0 --query "{rev:properties.latestRevisionName, ready:properties.latestReadyRevisionName}" -o json | ConvertFrom-Json
  if ($app.rev -eq $app.ready) { break }
  Start-Sleep -Seconds 10
}
"latest=$($app.rev) ready=$($app.ready)"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
$id = Invoke-RestMethod "$base/api/identity" -Headers $h -TimeoutSec 30
"modelRoutes=$($id.modelRoutes | ConvertTo-Json -Compress -Depth 5)"
$skills = Invoke-RestMethod "$base/api/skills" -Headers $h -TimeoutSec 30
$list = if ($skills.skills) { $skills.skills } else { $skills }
"skills=$(@($list).Count)"
$it = @($list) | Where-Object { $_.name -eq 'zero-touch-service-desk' -or $_.slug -eq 'zero-touch-service-desk' } | Select-Object -First 1
"itSkill=$($it | ConvertTo-Json -Compress -Depth 6)".Substring(0, [Math]::Min(1500, ("itSkill=$($it | ConvertTo-Json -Compress -Depth 6)").Length))
$servers = Invoke-RestMethod "$base/api/servers" -Headers $h -TimeoutSec 30
$servers | ConvertTo-Json -Compress -Depth 4 | ForEach-Object { $_.Substring(0, [Math]::Min(800, $_.Length)) }
$room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 30
foreach ($inst in @($room.instances)) {
  "instance: $($inst.name) | policy=$($inst.policy.source) skills=$(@($inst.policy.skills) -join ',') servers=$(@($inst.policy.servers) -join ',')"
}
$tok = $null
exit 0
