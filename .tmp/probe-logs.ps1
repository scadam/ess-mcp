Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where ContainerGroupName startswith ''job-desk-snprobe-8wb7u5r'' | project TimeGenerated, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
