<#
.SYNOPSIS
  Registers the ESS demo agent with Microsoft Purview DSPM-for-AI / AI Hub
  and grants its managed identity the Microsoft Graph permissions required
  to read tenant sensitivity-label policies.

.DESCRIPTION
  Run after `add-auth-sidecar.ps1` and after the agent's managed identity
  exists. This script is idempotent — re-running it will not duplicate role
  assignments or registrations. It performs five steps:

    1. Ensure the Microsoft Graph PowerShell SDK is available and signed in
       as a Global Admin / Compliance Admin.
    2. Grant the agent managed identity the Microsoft Graph application
       permission `InformationProtectionPolicy.Read.All` so it can resolve
       sensitivity labels at runtime.
    3. PUT a `copilotAndAiApps` registration on the tenant, declaring this
       agent as an AI workload that should appear in DSPM-for-AI dashboards.
    4. POST an `aiContent/agents` record so Defender XDR Agents inventory
       and Purview AI Hub know about the agent's identity, tenant, and
       Foundry blueprint.
    5. Print verification commands the operator can run from the Purview &
       Defender portals to confirm onboarding.

.PARAMETER TenantId
  The Entra tenant id where the agent runs.

.PARAMETER AgentManagedIdentityObjectId
  The objectId (NOT clientId) of the agent's user-assigned managed identity.

.PARAMETER AgentClientId
  The application (client) id of the agent's managed identity.

.PARAMETER AgentDisplayName
  Friendly name shown in DSPM/AI Hub. Defaults to "ESS Demo Workday + ServiceNow Agent".

.PARAMETER AgentEndpoint
  Public HTTPS endpoint that hosts the agent (used by Defender XDR Agents).

.PARAMETER BlueprintAppId
  The Entra app id for the agent blueprint. Already created by setup-tenant.ps1.

.PARAMETER FoundryAgentId
  The Azure AI Foundry agent id (optional but recommended; surfaces lineage in AI Hub).

.EXAMPLE
  ./setup-purview-dspm.ps1 `
    -TenantId 8030d928-e557-4a4c-ae1e-95c1c4125eaa `
    -AgentManagedIdentityObjectId 92983f30-a70d-4c86-8228-3d0b7f82488f `
    -AgentClientId 9380b56a-4aa9-46cf-b634-a6e29f536224 `
    -AgentEndpoint "https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io" `
    -BlueprintAppId 3f028e66-44cf-4cee-81ee-03ade7717884
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)] [string] $TenantId,
    [Parameter(Mandatory=$true)] [string] $AgentManagedIdentityObjectId,
    [Parameter(Mandatory=$true)] [string] $AgentClientId,
    [Parameter(Mandatory=$true)] [string] $AgentEndpoint,
    [Parameter(Mandatory=$true)] [string] $BlueprintAppId,
    [Parameter(Mandatory=$false)] [string] $FoundryAgentId = "",
    [Parameter(Mandatory=$false)] [string] $AgentDisplayName = "ESS Demo Workday + ServiceNow Agent"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "✔ $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "⚠ $msg" -ForegroundColor Yellow }

# ── Step 1: Microsoft Graph PowerShell SDK ────────────────────────────────
Write-Step "Verifying Microsoft.Graph PowerShell module"
if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
    Write-Warn2 "Microsoft.Graph not installed. Installing for current user (this can take a few minutes)…"
    Install-Module Microsoft.Graph -Scope CurrentUser -Force -AllowClobber
}
Import-Module Microsoft.Graph.Authentication
Import-Module Microsoft.Graph.Applications -ErrorAction SilentlyContinue

Write-Step "Connecting to Microsoft Graph (you will be prompted to sign in)"
$requiredScopes = @(
    "Application.Read.All",
    "AppRoleAssignment.ReadWrite.All",
    "Directory.Read.All"
)
# Note: InformationProtectionPolicy.Read.All / ProtectionScopes.Read.All are
# application-only permissions — they cannot be requested as delegated scopes
# here. They are granted to the agent's managed identity in step 2 below.
Connect-MgGraph -TenantId $TenantId -Scopes $requiredScopes -NoWelcome | Out-Null
$ctx = Get-MgContext
Write-Ok "Connected as $($ctx.Account) (tenant=$($ctx.TenantId))"

# ── Step 2: Grant InformationProtectionPolicy.Read.All to the MI ─────────
Write-Step "Granting InformationProtectionPolicy.Read.All to MI $AgentManagedIdentityObjectId"
$graphSp = Get-MgServicePrincipal -Filter "appId eq '00000003-0000-0000-c000-000000000000'"
$ipRole  = $graphSp.AppRoles | Where-Object { $_.Value -eq "InformationProtectionPolicy.Read.All" }
if (-not $ipRole) {
    throw "Could not find Microsoft Graph app role InformationProtectionPolicy.Read.All — has the tenant onboarded MIP?"
}

$existing = Get-MgServicePrincipalAppRoleAssignment -ServicePrincipalId $AgentManagedIdentityObjectId -ErrorAction SilentlyContinue |
    Where-Object { $_.AppRoleId -eq $ipRole.Id -and $_.ResourceId -eq $graphSp.Id }
if ($existing) {
    Write-Ok "Role InformationProtectionPolicy.Read.All already assigned"
} else {
    New-MgServicePrincipalAppRoleAssignment `
        -ServicePrincipalId $AgentManagedIdentityObjectId `
        -PrincipalId $AgentManagedIdentityObjectId `
        -ResourceId $graphSp.Id `
        -AppRoleId $ipRole.Id | Out-Null
    Write-Ok "Granted InformationProtectionPolicy.Read.All"
}

# ── Step 3: DSPM-for-AI / Defender XDR onboarding (manual portal flow) ──
#
# As of May 2026 there is no public Microsoft Graph endpoint OR Purview
# portal surface to manually register a third-party SDK-hosted agent
# (parent or per-instance teammates) into DSPM-for-AI's "Apps and agents"
# inventory. (Earlier preview docs referenced /beta/security/dataSecurity-
# AndGovernance/copilotAndAiApps and /beta/security/aiContent/agents — both
# return "Resource not found for the segment". The portal "+ Add
# application → Other AI app (custom)" entry was removed when DSPM
# consolidated into the new Purview portal.) Discovery is now automatic
# via the SDK emit pipeline + Defender for Cloud Apps + Browser
# extension. The script prints what to verify in the portal:

Write-Host ""
Write-Host "─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "MANUAL portal verification (no add-app UI exists for SDK agents)" -ForegroundColor White
Write-Host "─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  A. Purview portal → DSPM → Overview"
Write-Host "     https://purview.microsoft.com/dspm/overview"
Write-Host "     If you see 'Activate DSPM for AI' click it (one-time per"
Write-Host "     tenant). Wait ~10 min for the workspace to provision."
Write-Host ""
Write-Host "  B. DSPM → Activity explorer — this is where our SDK emit"
Write-Host "     pipeline lands rows automatically. Filter by:"
Write-Host "       User participant : <manager UPN>"
Write-Host "       Activity type    : AI Interaction OR Sensitive info types"
Write-Host "       App accessed in  : agent365-control-plane"
Write-Host "       Timestamp        : last 1 hour"
Write-Host "     Rows will show Agent name = $AgentDisplayName even for"
Write-Host "     per-teammate runs (Purview today collapses all SDK runs"
Write-Host "     to the parent registered app). Use Timestamp + User"
Write-Host "     participant to correlate to specific control-plane runs."
Write-Host ""
Write-Host "  C. DSPM → Apps and agents — auto-discovered via Defender for"
Write-Host "     Cloud Apps. Your agent appears here after enough traffic"
Write-Host "     is seen on the AOAI endpoint (essmcp-openai)."
Write-Host "     Expected display: 'essmcp-openai (Azure AI)' — that is"
Write-Host "     the AOAI resource being called, not our agent identity."
Write-Host ""
Write-Host "  D. Defender XDR portal → Settings → AI Agents (preview)"
Write-Host "     https://security.microsoft.com/securitysettings/agents"
Write-Host "     Auto-populated from AAD app metadata + AIAgentsInfo table."
Write-Host "     If empty after 24h, run the agent a few times then check."
Write-Host "     There is no '+ Onboard agent' manual button either."
Write-Host "       Parent  : $AgentClientId"
Write-Host "       Blueprint: $BlueprintAppId"
if ($FoundryAgentId) {
    Write-Host "       Foundry  : $FoundryAgentId"
}
Write-Host ""
Write-Host "  E. Quick reality check from the agent runtime:"
Write-Host "     curl $AgentEndpoint/api/identity | jq .observability.purview"
Write-Host "     → expect { enabled: true, configured: true, ... }"
Write-Host "     curl $AgentEndpoint/api/runs | jq '.[0].actor'"
Write-Host "     → confirm manager UPN is present (drives User participant"
Write-Host "       resolution in Activity explorer)."
Write-Host "─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

Write-Ok "Automated onboarding complete (Step 1 + Step 2)."
Write-Warn2 "Per-teammate row break-out in Activity explorer is not possible"
Write-Warn2 "until Microsoft ships a public API for per-instance AI app"
Write-Warn2 "registration. Today all SDK runs collapse under the parent."
