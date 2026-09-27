Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$query = 'ContainerAppConsoleLogs | where TimeGenerated > ago(90m) | where ContainerGroupName startswith ''job-desk-snprobe-800avdh'' | where Log has ''user_name'' or Log has ''grant admin'' | project Log | take 10'
& .\.tmp\la-query.ps1 -Query $query
exit 0
