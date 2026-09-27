Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated between (datetime(2026-09-25T22:42:45Z) .. datetime(2026-09-25T22:44:30Z)) | where ContainerAppName == ''ca-autopilot-caldova-78f0'' | project TimeGenerated, Log | order by TimeGenerated asc | take 60'
& .\.tmp\la-query.ps1 -Query $query
exit 0
