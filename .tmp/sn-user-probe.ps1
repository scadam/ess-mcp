param([string] $User = 'kian.lambert', [string] $Instance = 'https://dev407392.service-now.com')
$ErrorActionPreference = 'Stop'
# Read-only probe of the Table/Catalog APIs the MCP tools call, signed in as a demo person (password from $env:SN_DEMO_PW).
$headers = @{ Accept = 'application/json'; Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${User}:$($env:SN_DEMO_PW)")) }
$paths = 'incident', 'problem', 'change_request', 'sc_req_item', 'sysapproval_approver', 'kb_knowledge', 'sc_cat_item',
         'alm_hardware', 'cmdb_ci_computer', 'task_sla', 'sys_user', 'sys_user_group', 'sys_user_grmember', 'incident_task', 'sys_attachment'
foreach ($table in $paths) {
  try {
    $r = Invoke-RestMethod "$Instance/api/now/table/$table" -Headers $headers -Body @{ sysparm_limit = '3'; sysparm_fields = 'sys_id' } -TimeoutSec 60
    "{0,-22} ok   rows={1}" -f $table, @($r.result).Count
  } catch { "{0,-22} FAIL {1}" -f $table, $_.Exception.Response.StatusCode.value__ }
}
try {
  $r = Invoke-RestMethod "$Instance/api/sn_sc/servicecatalog/items" -Headers $headers -Body @{ sysparm_limit = '3' } -TimeoutSec 60
  "{0,-22} ok   rows={1}" -f 'sn_sc items', @($r.result).Count
} catch { "{0,-22} FAIL {1}" -f 'sn_sc items', $_.Exception.Response.StatusCode.value__ }
exit 0
