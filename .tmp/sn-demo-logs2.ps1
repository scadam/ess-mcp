Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(30m) | where Log has ''"incident"'' or Log has ''POST /api/events/servicenow'' or Log has ''case.sweep'' or Log has ''INC00100'' | project TimeGenerated, ContainerGroupName, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
