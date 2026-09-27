Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(40m) | where ContainerGroupName startswith ''job-desk-servicenow-tp3dtax'' or ContainerGroupName startswith ''job-desk-servicenow-u0yd1pq'' | where Log has ''incident'' or Log has ''done'' or Log has ''Traceback'' | project TimeGenerated, ContainerGroupName, Log | order by TimeGenerated asc | take 20'
& .\.tmp\la-query.ps1 -Query $query
"--- host events"
$query2 = 'ContainerAppConsoleLogs | where TimeGenerated > ago(40m) | where ContainerAppName == ''ca-autopilot-caldova-78f0'' | where Log has ''/api/events/servicenow'' or Log has ''case.event'' or Log has ''webhook'' | project TimeGenerated, Log | order by TimeGenerated asc | take 30'
& .\.tmp\la-query.ps1 -Query $query2
exit 0
