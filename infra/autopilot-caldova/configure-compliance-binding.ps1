[CmdletBinding()]
param(
  [string] $InstanceName = 'Compliance Agent',
  [string[]] $RequesterUpns = @('admin@caldova74201480.onmicrosoft.com'),
  [string] $EvidenceFile = '',
  [string] $Blueprint = '77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde',
  [switch] $SetManagerIfMissing,
  [string] $ManagerUpn = 'admin@caldova74201480.onmicrosoft.com'
)
# Builds AUTOPILOT_COMPLIANCE_BINDINGS from VERIFIED directory relationships: the
# agent identity spawned from the Caldova blueprint, its same-named agentic user,
# that user's Entra manager, explicit requester accounts and the evidence paths.
$ErrorActionPreference = 'Stop'
$graph = 'https://graph.microsoft.com/v1.0'

function Get-Graph([string] $Url) {
  $out = az rest --method GET --url $Url --headers 'ConsistencyLevel=eventual' -o json
  if ($LASTEXITCODE -ne 0) { throw 'Graph read failed.' }
  $out | Out-String | ConvertFrom-Json
}

$instances = @((Get-Graph "$graph/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$Blueprint'&`$select=id,appId,displayName").value)
if (-not $instances) { throw 'No agent identity instance exists for the blueprint yet. Hire the agent first.' }
$instance = @($instances | Where-Object displayName -eq $InstanceName)
if ($instance.Count -ne 1) {
  $names = ($instances | ForEach-Object displayName) -join ', '
  throw "Expected exactly one instance named '$InstanceName'; found: $names"
}
$instance = $instance[0]
# An agent identity's appId equals its object id; never bind a null instance.
$instanceAppId = if ($instance.appId) { $instance.appId } else { $instance.id }
if (-not $instanceAppId) { throw 'The agent identity has no app id.' }
$users = @((Get-Graph "$graph/users?`$filter=displayName eq '$($InstanceName.Replace("'", "''"))'").value)
if ($users.Count -ne 1) { throw "Expected exactly one agentic user named '$InstanceName'." }
$agentUser = $users[0]

$manager = $null
try { $manager = Get-Graph "$graph/users/$($agentUser.id)/manager" } catch { $manager = $null }
if (-not $manager.id) {
  if (-not $SetManagerIfMissing) { throw 'The agentic user has no Entra manager. Re-run with -SetManagerIfMissing.' }
  $managerUser = Get-Graph "$graph/users/$ManagerUpn"
  $body = New-TemporaryFile
  try {
    @{ '@odata.id' = "$graph/users/$($managerUser.id)" } | ConvertTo-Json | Set-Content $body -Encoding utf8NoBOM
    az rest --method PUT --url "$graph/users/$($agentUser.id)/manager/`$ref" --headers 'Content-Type=application/json' --body "@$body" -o none
    if ($LASTEXITCODE -ne 0) { throw 'Setting the agentic user manager failed.' }
  } finally { Remove-Item $body -ErrorAction SilentlyContinue }
  $manager = Get-Graph "$graph/users/$($agentUser.id)/manager"
}

$requesters = foreach ($upn in $RequesterUpns) { (Get-Graph "$graph/users/$upn").id }
$paths = @()
if ($EvidenceFile) { $paths = @((Get-Content $EvidenceFile -Raw | ConvertFrom-Json).evidencePaths) }

$binding = [ordered]@{
  name = $InstanceName
  instanceAppId = $instanceAppId
  agenticUserId = $agentUser.id
  managerId = $manager.id
  requesterIds = @($requesters)
  evidencePaths = $paths
}
[pscustomobject]@{
  instanceObjectId = $instance.id
  agenticUserUpn = $agentUser.userPrincipalName
  manager = $manager.userPrincipalName
  bindings = ConvertTo-Json @($binding) -Depth 5 -Compress
} | ConvertTo-Json -Depth 5
