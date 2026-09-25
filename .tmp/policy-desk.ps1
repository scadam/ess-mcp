$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
# Additive only: the desk playbooks and assignment skills for each function colleague with a saved operator policy.
$adds = @{
  'HR Agent'           = @{ skills = @('hr-second-line'); servers = @('workday') }
  'Supply Chain Agent' = @{ skills = @('supply-second-line', 'supplier-onboarding-panel'); servers = @('coupa') }
  'Compliance Agent'   = @{ skills = @('compliance-second-line'); servers = @('salesforce', 'coupa') }
}
$room = Invoke-RestMethod "$base/api/control-room" -Headers $h -TimeoutSec 30
foreach ($inst in @($room.instances)) {
  if (-not $adds.ContainsKey($inst.name)) { continue }
  if ($inst.policy.source -ne 'operator') { "skip $($inst.name): $($inst.policy.source) policy applies (skills: $(@($inst.policy.skills) -join ','))"; continue }
  $skills = @(@($inst.policy.skills) + $adds[$inst.name].skills | Sort-Object -Unique)
  $servers = @(@($inst.policy.servers) + $adds[$inst.name].servers | Sort-Object -Unique)
  $body = @{ skills = $skills; servers = $servers } | ConvertTo-Json -Compress
  $r = Invoke-RestMethod "$base/api/control-room/instances/$($inst.key)/policy" -Method Put -Headers $h -ContentType 'application/json' -Body $body -TimeoutSec 30
  "updated $($inst.name): skills=$(@($r.policy.skills) -join ',') servers=$(@($r.policy.servers) -join ',') persisted=$($r.persisted)"
}
$tok = $null
exit 0
