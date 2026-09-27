Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(30m) | where ContainerGroupName startswith ''job-desk-snprobe-800avdh'' | project TimeGenerated, Log | order by TimeGenerated asc | take 40'
& .\.tmp\la-query.ps1 -Query $query
exit 0
