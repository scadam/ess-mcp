Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(90m) | where Log has ''demo password present'' or Log has ''basic admin'' or Log has ''grant kian'' or Log has ''basic kian'' or Log has ''api access policies'' or Log has ''property glide'' or Log has ''kian.lambert {'' | project TimeGenerated, ContainerGroupName, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
