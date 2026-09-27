[CmdletBinding()]
param(
  # Leave Kian's battery incident and the Salesforce cases for later (raise them live instead).
  [switch] $NoSeed
)
# Puts the demo back to its starting line: Coupa's simulated data to its seed, a clean control room and case desk,
# last run's demo incidents and cases closed, the ServiceNow demo people restored, and fresh demo records raised so
# the colleagues start working them straight away. Takes about ten minutes.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription
$provision = Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1'

# 1. Close last run's demo incidents and cases first, as the integration account: the desk's first sweep after the
#    reset skips records the integration account changed last, so they can't come back as new cases.
& $provision -System servicenow -Mode reset
& $provision -System salesforce -Mode reset
Write-Host "1/5 Last run's demo incidents and cases closed."

# 2. Coupa keeps its simulated state in memory, so a restart returns the invoices to their seeded exceptions.
$coupa = 'essmcp-caldova-coupa'
$revision = (Get-DemoApp $coupa).properties.latestReadyRevisionName
Invoke-DemoArm -Method Post -Path ("/subscriptions/$DemoSubscription/resourceGroups/$DemoResourceGroup/providers/" +
  "Microsoft.App/containerApps/$coupa/revisions/$revision/restart?api-version=2024-03-01") | Out-Null
Start-Sleep -Seconds 20
Wait-DemoApp $coupa | Out-Null
Write-Host '2/5 Coupa is back to its seeded invoices.'

# 3. Clears cases, runs, activity, chat memory and waiting approvals (approved skills stay); the desk restarts and
#    its first sweep, about 30 seconds later, finds the Coupa invoice exceptions on its own.
$token = Get-DemoOperatorToken
$result = Invoke-RestMethod -Method Post "$DemoHostUrl/api/control-room/reset" -Headers @{ Authorization = "Bearer $token" } `
  -ContentType 'application/json' -Body '{"confirm":"RESET"}' -TimeoutSec 180
$token = $null
Write-Host "3/5 Control room reset ($($result.removedRecords) stored records cleared)."

# 4. ServiceNow: restore the people, lock-out and devices, then raise Kian's incident.
& $provision -System servicenow -Mode setup
if (-not $NoSeed) { & $provision -System servicenow -Mode demo -Scenario battery }
Write-Host '4/5 ServiceNow ready.'

# 5. Salesforce: raise fresh demo cases.
if (-not $NoSeed) { & $provision -System salesforce -Mode demo }
Write-Host '5/5 Salesforce ready.'
Write-Host "`nWatch the colleagues pick the cases up: $DemoHostUrl/control-plane#/cases"
exit 0
