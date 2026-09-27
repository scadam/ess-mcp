Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(60m) | where ContainerAppName == ''ca-autopilot-caldova-78f0'' | where Log has ''INC0010007'' or Log has ''case.turn'' or Log has ''case.sweep'' or Log has ''Case desk'' or Log has ''case desk'' | project TimeGenerated, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
