$ErrorActionPreference = 'Continue'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
"--- one probe as kian.lambert, with ServiceNow's error body"
$headers = @{ Accept = 'application/json'; Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("kian.lambert:$($env:SN_DEMO_PW)")) }
try { (Invoke-WebRequest 'https://dev407392.service-now.com/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id' -Headers $headers -UseBasicParsing -TimeoutSec 60).StatusCode }
catch { "HTTP $($_.Exception.Response.StatusCode.value__): $($_.ErrorDetails.Message)" }
"--- setup job log (sign_in / roles)"
$query = 'ContainerAppConsoleLogs | where ContainerGroupName startswith ''job-desk-servicenow-je0p19b'' | where Log has ''sign_in'' or Log has ''role'' or Log has ''Traceback'' | project Log | take 20'
& .\.tmp\la-query.ps1 -Query $query
exit 0
