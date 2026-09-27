Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(40m) | where ContainerGroupName has ''snprobe'' or ContainerName == ''probe'' | project TimeGenerated, ContainerGroupName, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
