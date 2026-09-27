Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(60m) | where ContainerGroupName startswith ''job-desk-snprobe-ge0sm19'' | project TimeGenerated, Log | order by TimeGenerated asc | take 60'
& .\.tmp\la-query.ps1 -Query $query
exit 0
