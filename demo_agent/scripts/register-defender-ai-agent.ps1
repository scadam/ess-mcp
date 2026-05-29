<#
.SYNOPSIS
    Onboards the ESS Hosted Demo Agent into Microsoft Defender XDR.

.DESCRIPTION
    Performs every step that CAN be automated (managed-identity permissions for
    Defender XDR Advanced Hunting + alerts read), then prints the manual portal
    flow for the two surfaces that require it (Defender for Cloud Apps "Discover
    AI agents and assets" and Defender XDR Settings -> AI Agents preview), and
    finally runs the verification KQL through Graph to confirm the agent is
    visible in the AIAgentsInfo / CloudAppEvents tables.

    Pre-reqs:
      - Run as Tenant Global Reader + Security Administrator (or higher).
      - Microsoft.Graph PowerShell module 2.x installed.
      - You are signed in to az CLI on the demo subscription.

.NOTES
    Sister script to:
      - register-purview-sits.ps1     (Purview custom Sensitive Info Types)
      - setup-purview-dspm.ps1        (Purview DSPM-for-AI label propagation)
      - setup-tenant.ps1              (one-shot bootstrap)
#>

[CmdletBinding()]
param(
    [string] $TenantId               = '8030d928-e557-4a4c-ae1e-95c1c4125eaa',
    [string] $TenantDomain           = 'M365CPI81302533.onmicrosoft.com',
    [string] $ParentAgentAppId       = 'ed4046aa-a3ef-4685-a73d-ecda5a4f01da',
    [string] $BlueprintAppId         = '3f028e66-44cf-4cee-81ee-03ade7717884',
    [string] $ManagedIdentityObjectId = '92983f30-a70d-4c86-8228-3d0b7f82488f',
    [string] $AgentFqdn              = 'ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io',
    [switch] $SkipPermissionGrant,
    [switch] $SkipVerification
)

$ErrorActionPreference = 'Stop'
$WarningPreference     = 'Continue'

function Write-Header([string] $text) {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor DarkCyan
    Write-Host (" $text") -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor DarkCyan
}

# ----------------------------------------------------------------------------
# 1. Grant the host managed identity the Defender XDR app roles it needs to
#    self-verify agent telemetry from inside the container.
# ----------------------------------------------------------------------------
# Microsoft Graph (00000003-0000-0000-c000-000000000000) — Advanced Hunting +
# read-only Security app roles are exposed under Graph, NOT under the legacy
# Microsoft Threat Protection API.

$GraphAppId            = '00000003-0000-0000-c000-000000000000'
$RolesToGrant = @(
    @{ Name = 'ThreatHunting.Read.All';   Description = 'Advanced Hunting query API' },
    @{ Name = 'SecurityEvents.Read.All';  Description = 'Read security alerts & incidents' },
    @{ Name = 'SecurityAlert.Read.All';   Description = 'Defender XDR alert details' },
    @{ Name = 'SecurityIncident.Read.All';Description = 'Defender XDR incident details' }
)

function Connect-GraphIfNeeded {
    $ctx = $null
    try { $ctx = Get-MgContext } catch { }
    if (-not $ctx -or $ctx.TenantId -ne $TenantId) {
        Write-Host "Connecting to Microsoft Graph (tenant $TenantId)..." -ForegroundColor Yellow
        Connect-MgGraph -TenantId $TenantId -Scopes @(
            'Application.Read.All',
            'AppRoleAssignment.ReadWrite.All',
            'Directory.Read.All'
        ) -NoWelcome | Out-Null
    }
}

function Grant-AppRoleToMI {
    param(
        [Parameter(Mandatory)] [string] $ResourceAppId,
        [Parameter(Mandatory)] [string] $RoleName,
        [Parameter(Mandatory)] [string] $ManagedIdentityObjectId
    )

    $resourceSp = Get-MgServicePrincipal -Filter "appId eq '$ResourceAppId'" -ErrorAction Stop
    if (-not $resourceSp) {
        throw "Resource service principal not found for appId $ResourceAppId"
    }
    $appRole = $resourceSp.AppRoles | Where-Object { $_.Value -eq $RoleName -and $_.AllowedMemberTypes -contains 'Application' }
    if (-not $appRole) {
        Write-Warning "AppRole '$RoleName' not found on resource $ResourceAppId — skipping."
        return
    }

    $existing = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $ManagedIdentityObjectId -ErrorAction SilentlyContinue |
        Where-Object { $_.AppRoleId -eq $appRole.Id -and $_.ResourceId -eq $resourceSp.Id }
    if ($existing) {
        Write-Host "  [ok] $RoleName already granted." -ForegroundColor DarkGreen
        return
    }

    New-MgServicePrincipalAppRoleAssignment `
        -ServicePrincipalId $ManagedIdentityObjectId `
        -PrincipalId        $ManagedIdentityObjectId `
        -ResourceId         $resourceSp.Id `
        -AppRoleId          $appRole.Id | Out-Null
    Write-Host "  [granted] $RoleName" -ForegroundColor Green
}

if (-not $SkipPermissionGrant) {
    Write-Header 'STEP 1 / 4  Grant Defender XDR read permissions to the host managed identity'

    if (-not (Get-Module Microsoft.Graph.Authentication -ListAvailable)) {
        Write-Host 'Installing Microsoft.Graph PowerShell module (current user scope)...' -ForegroundColor Yellow
        Install-Module Microsoft.Graph -Scope CurrentUser -Force -AllowClobber
    }
    Import-Module Microsoft.Graph.Authentication            -ErrorAction Stop
    Import-Module Microsoft.Graph.Applications              -ErrorAction Stop

    Connect-GraphIfNeeded

    foreach ($role in $RolesToGrant) {
        try {
            Grant-AppRoleToMI -ResourceAppId $GraphAppId -RoleName $role.Name -ManagedIdentityObjectId $ManagedIdentityObjectId
        } catch {
            Write-Warning "Failed to grant $($role.Name): $($_.Exception.Message)"
        }
    }
} else {
    Write-Header 'STEP 1 / 4  (skipped — -SkipPermissionGrant set)'
}

# ----------------------------------------------------------------------------
# 2. Manual portal flow — Defender for Cloud Apps "Discover AI agents".
# ----------------------------------------------------------------------------
Write-Header 'STEP 2 / 4  Defender for Cloud Apps — Discover AI agents and assets'
@"
Open:   https://security.microsoft.com/discoveryReports?tid=$TenantId
Then:
  1. Navigate to Cloud apps -> Discovery -> AI agents and assets.
  2. Toggle "Enable AI agents and assets discovery" ON if not already on.
  3. Open the Tenant identity column and confirm that
     '$ParentAgentAppId' is present (it will appear after the next agent
     run — Defender fingerprints outbound traffic to
     agent365.svc.cloud.microsoft).
  4. Pin the report to your hunting dashboard:
     '+ Pin to dashboard' -> 'ESS Hosted Agent — discovered AI assets'.
"@ | Write-Host

# ----------------------------------------------------------------------------
# 3. Manual portal flow — Defender XDR Settings -> AI Agents (preview).
# ----------------------------------------------------------------------------
Write-Header 'STEP 3 / 4  Defender XDR Settings — AI Agents (preview)'
@"
Open:   https://security.microsoft.com/securitysettings/agents?tid=$TenantId
Then:
  1. Click 'Onboard agent' -> choose 'Other (SDK)'.
  2. Paste these values:
        Tenant id              : $TenantId
        Agent app id (parent)  : $ParentAgentAppId
        Blueprint app id       : $BlueprintAppId
        Public endpoint        : https://$AgentFqdn
        Owner UPN              : svasireddy@$TenantDomain
  3. Save. Defender will create the agent record within ~10 minutes; the
     'AIAgentsInfo' table will start returning rows for this id.
  4. Optional: under 'Detection rules' click 'Create detection rule' and
     import the four ESS rules listed in demo_agent/docs/DEFENDER_HUNTING.md
     section 7.
"@ | Write-Host

# ----------------------------------------------------------------------------
# 4. Verification — call the Graph Advanced Hunting API ourselves and report.
# ----------------------------------------------------------------------------
if (-not $SkipVerification) {
    Write-Header 'STEP 4 / 4  Verification — Graph Advanced Hunting query'

    Connect-GraphIfNeeded
    $token = (Get-MgContext).AuthType
    Write-Host "Auth context: $token" -ForegroundColor DarkGray

    $kql = @"
union
  (AIAgentsInfo
     | where AIAgentId in ('$ParentAgentAppId') or AIAgentName has 'ESS'
     | project Source='AIAgentsInfo', Timestamp, AIAgentId, AIAgentName, AgentStatus, CreatorAccountUpn),
  (CloudAppEvents
     | where Timestamp > ago(7d)
     | where AccountObjectId == '$ParentAgentAppId' or AccountDisplayName has 'ESS'
     | top 5 by Timestamp
     | project Source='CloudAppEvents', Timestamp, AIAgentId=tostring(AccountObjectId),
               AIAgentName=AccountDisplayName, AgentStatus=ActionType, CreatorAccountUpn=AccountUpn)
| sort by Timestamp desc
"@

    $body = @{ Query = $kql } | ConvertTo-Json -Compress -Depth 4

    try {
        $resp = Invoke-MgGraphRequest -Method POST -Uri 'https://graph.microsoft.com/v1.0/security/runHuntingQuery' -Body $body -ContentType 'application/json'
        if ($resp.results -and $resp.results.Count -gt 0) {
            Write-Host ("Found {0} rows referencing the ESS agent:" -f $resp.results.Count) -ForegroundColor Green
            $resp.results | Format-Table -AutoSize
        } else {
            Write-Warning 'Query succeeded but returned 0 rows.'
            Write-Host @"
This is expected if:
  - You have not yet completed the portal step (3) above, OR
  - The agent has not been invoked since onboarding (Defender ingestion
    is normally < 30 minutes once the agent runs at least once).

Trigger a run from the control plane:
    https://$AgentFqdn/control-plane

Then re-run:  pwsh -File demo_agent/scripts/register-defender-ai-agent.ps1 -SkipPermissionGrant
"@ -ForegroundColor Yellow
        }
    } catch {
        Write-Warning "Verification call failed: $($_.Exception.Message)"
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message -ForegroundColor DarkRed }
        Write-Host @"
Most common cause: the signed-in user lacks 'ThreatHunting.Read.All' delegated
scope. Either:
  - rerun with Connect-MgGraph -Scopes 'ThreatHunting.Read.All' (admin consent
    required for the Microsoft Graph PowerShell SP), OR
  - run the verification from inside the container, which now holds the MI
    permission granted in step 1:
       curl https://$AgentFqdn/api/defender-status
"@ -ForegroundColor Yellow
    }
} else {
    Write-Header 'STEP 4 / 4  (skipped — -SkipVerification set)'
}

Write-Header 'Done'
@"
Next steps:
  - Open https://$AgentFqdn/control-plane and watch the "Defender hunting"
    surfaces tile (it now opens Advanced Hunting with a pre-built KQL).
  - See demo_agent/docs/DEFENDER_HUNTING.md for the full KQL playbook.
  - See demo_agent/docs/AGENT365_VALUE.md for the end-to-end Agent 365
    value matrix this agent now lights up.
"@ | Write-Host -ForegroundColor Green
