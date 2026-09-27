$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
"--- host deploy"
Get-Content .tmp\ship-host.txt -Tail 4 -ErrorAction SilentlyContinue
"--- setup job log (sign_in / roles)"
& .\.tmp\la-query.ps1 -Query "ContainerAppConsoleLogs | where ContainerGroupName startswith 'job-desk-servicenow-je0p19b' | where Log has_any ('sign_in', '\"role\"', 'Autopilot Demo Users', 'Traceback') | project Log | take 20"
"--- one probe as kian.lambert, with ServiceNow's error body"
$headers = @{ Accept = 'application/json'; Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("kian.lambert:$($env:SN_DEMO_PW)")) }
try { (Invoke-WebRequest 'https://dev407392.service-now.com/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id' -Headers $headers -UseBasicParsing -TimeoutSec 60).StatusCode }
catch { "HTTP $($_.Exception.Response.StatusCode.value__): $($_.ErrorDetails.Message)" }
exit 0
