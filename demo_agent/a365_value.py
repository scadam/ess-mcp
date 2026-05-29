"""Agent 365 value catalog — HIGH-impact features for SDK-hosted agents.

This module is the single source of truth for "what does Agent 365 do for
*this* agent". It is consumed by `/api/a365-value` (web.py) and rendered
in the control plane "Agent 365 value" panel.

Each entry answers four operator questions:

  1. **Data in** — what signal does the agent (or A365 fabric) emit that
     unlocks this capability?
  2. **Why it matters** — the pitch in one line.
  3. **Where to see it** — pre-built portal deep link(s).
  4. **How to query it** — a copy-paste KQL or PowerShell snippet ready
     for the linked portal.

Provenance: feature names, pillars, and pitches mirror the public
``a365-app/src/data/agent365-data.json`` value matrix, narrowed to the
26 entries that score HIGH for the **sdk** agent archetype.
"""

from __future__ import annotations

from typing import Any


STATUS_ORDER = ("active", "configured", "manual", "roadmap")

STATUS_LABEL = {
    "active": "Active",
    "configured": "Configured",
    "manual": "Manual step",
    "roadmap": "Roadmap",
}

# Identifiers re-used across the catalog.
TENANT_ID         = "8030d928-e557-4a4c-ae1e-95c1c4125eaa"
TENANT_DOMAIN     = "M365CPI81302533.onmicrosoft.com"
PARENT_AGENT_APP  = "ed4046aa-a3ef-4685-a73d-ecda5a4f01da"
BLUEPRINT_APP     = "3f028e66-44cf-4cee-81ee-03ade7717884"
BLUEPRINT_SP      = "612885df-960e-4900-b065-cc3ff00287bf"
HOST_MI           = "92983f30-a70d-4c86-8228-3d0b7f82488f"
AGENT_FQDN        = "ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io"

# Bring-Your-Own MCP servers registered via the Agent 365 develop-mcp CLI.
# Calls through the Microsoft Tooling Gateway (Copilot Studio, VS Code MCP
# client, Claude Code, GitHub Copilot CLI) appear in CloudAppEvents as
# `ActionType == "ExecuteToolByGateway"` with the server name in RawEventData.
# Calls from our own demo_agent runtime do NOT flow through the Tooling Gateway
# and will NOT appear under that ActionType.
BYO_MCP_SERVERS   = ("ext_ESSWorkday", "ext_ESSServiceNow2", "ext_ESSCoupa")
BYO_MCP_NOTE      = (
    "// Once these MCP servers are registered as BYO MCP and called from\n"
    "// Copilot Studio / VS Code / Claude / GH CLI, this query returns those\n"
    "// invocations via ActionType == \"ExecuteToolByGateway\". Calls from our\n"
    "// own demo_agent runtime don't flow through the Tooling Gateway and won't\n"
    "// appear here.\n"
)


def _byo_mcp_query(label: str) -> dict[str, str]:
    """Return the canonical KQL card for BYO MCP Tooling Gateway invocations."""
    server_list = ", ".join(f'"{s}"' for s in BYO_MCP_SERVERS)
    return {
        "label": label,
        "syntax": "kql",
        "portal": "defender-hunting",
        "code": (
            "// ===== ESS Agent 365 · BYO MCP Tooling Gateway invocations =====\n"
            + BYO_MCP_NOTE
            + "CloudAppEvents\n"
            "| where Timestamp > ago(24h)\n"
            "| where ActionType == \"ExecuteToolByGateway\"\n"
            f"| where RawEventData has_any ({server_list})\n"
            "| project-reorder Timestamp, AccountObjectId, AccountDisplayName, ActionType, ApplicationId, RawEventData\n"
            "| sort by Timestamp desc\n"
            "| take 50"
        ),
    }


def _f(
    *,
    id: str,
    name: str,
    category: str,
    pillar: str,
    status: str,
    summary: str,
    pitch: str,
    flow_in: list[str],
    flow_out: list[str],
    wired: list[str],
    portals: list[dict[str, str]],
    queries: list[dict[str, str]] | None = None,
    docs: list[str] | None = None,
    ga: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "category": category,
        "pillar": pillar,
        "status": status,
        "summary": summary,
        "pitch": pitch,
        "flow": {"in": flow_in, "out": flow_out},
        "wired": wired,
        "portals": portals,
        "queries": queries or [],
        "docs": docs or [],
        "ga": ga,
    }


def feature_catalog() -> list[dict[str, Any]]:
    """Return the 26 HIGH-value SDK features with this agent's wired status."""

    advhunt = f"https://security.microsoft.com/v2/advanced-hunting?tid={TENANT_ID}"
    purview_audit = "https://purview.microsoft.com/audit/auditsearch"

    return [
        # ============================================================== Entra
        _f(
            id="agent-id",
            name="Entra Agent ID",
            category="Entra",
            pillar="Observe",
            status="active",
            summary="Parent identity + per-user agent identities provisioned and used at runtime.",
            pitch="Agent 365 starts with an addressable directory identity. One parent app id and three per-user teammates are already in Entra.",
            flow_in=[
                "Boot: container reads ENTRA_AGENT_APP_ID + tenant from env",
                "Sidecar exchanges MSI → Agent Identity token (fmi_path)",
                "Every downstream call carries the Agent Identity claim",
            ],
            flow_out=[
                "AADSpnSignInEventsBeta — one row per outbound call",
                "Entra audit log — directory writes against per-user teammates",
            ],
            wired=[
                "demo_agent/identity.py — AgentIdentityContext.from_env loads identity on boot",
                "demo_agent/oauth.py — sidecar token exchange for every downstream call",
            ],
            portals=[
                {"label": "Entra · Parent agent app", "url": f"https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/Overview/appId/{PARENT_AGENT_APP}"},
                {"label": "Entra · Agent Identities blade", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/AgentIdentitiesBlade"},
            ],
            queries=[
                {
                    "label": "Defender · Recent sign-ins by this agent",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Recent sign-ins by this agent =====\n"
                        "// Validated columns: Timestamp, Application, ApplicationId, ResourceDisplayName,\n"
                        "// IPAddress, ErrorCode (per public AADSpnSignInEventsBeta schema).\n"
                        "AADSpnSignInEventsBeta\n"
                        f"| where ApplicationId == \"{PARENT_AGENT_APP}\"\n"
                        "| where Timestamp > ago(24h)\n"
                        "| project-reorder Timestamp, Application, ResourceDisplayName, IPAddress, ErrorCode, CorrelationId\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                _byo_mcp_query("Defender · BYO MCP Tooling Gateway invocations"),
            ],
        ),
        _f(
            id="governance",
            name="Agent Identity Governance (Access Packages)",
            category="Entra",
            pillar="Govern",
            status="manual",
            summary="Per-user teammate identities are first-class principals for Access Packages + Access Reviews.",
            pitch="Custom SDK agents rarely get IGA coverage. A365 makes the parent + per-user identities first-class principals.",
            flow_in=[
                "Per-user teammate apps tagged servicePrincipalType=Application",
                "Blueprint exposes scopes that an access package can grant",
            ],
            flow_out=[
                "Entra ID Governance · Access reviews queue",
                "AuditLogs / IdentityGovernance category events",
            ],
            wired=[
                "Parent + per-user identities tagged for assignments",
            ],
            portals=[
                {"label": "Entra ID Governance · Access packages", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_ERM/DashboardBlade/~/elmEntitlement"},
            ],
            queries=[
                {
                    "label": "Graph · List access reviews touching this agent",
                    "syntax": "powershell",
                    "portal": "graph-explorer",
                    "code": (
                        "# Note: access-review scope is stored as a Graph OData query string in\n"
                        "# .scope.query (e.g. \"/servicePrincipals/<spOid>\"), so we match by\n"
                        "# the SP object id, not the appId. Resolve the SP first.\n"
                        "Connect-MgGraph -Scopes 'AccessReview.Read.All','Application.Read.All'\n"
                        f"$sp = Get-MgServicePrincipal -Filter \"appId eq '{PARENT_AGENT_APP}'\" -Select id,displayName,appId\n"
                        "Get-MgIdentityGovernanceAccessReviewDefinition -All |\n"
                        "  Where-Object { $_.Scope.AdditionalProperties.query -match $sp.Id } |\n"
                        "  Select-Object Id, DisplayName, Status, CreatedDateTime"
                    ),
                },
            ],
        ),
        _f(
            id="ca",
            name="Conditional Access (agent-distinguishable)",
            category="Entra",
            pillar="Secure",
            status="configured",
            summary="Per-user teammate tokens carry the actor + agent claims that CA can target.",
            pitch="You own the code → decorate every outbound token with agent context. CA can require device, location, or risk on agent calls.",
            flow_in=[
                "Token exchange sets agent_id_override + agentic_user_id_override",
                "Tokens hit downstream APIs through Conditional Access enforcement",
            ],
            flow_out=[
                "SigninLogs · servicePrincipalSignIns with conditionalAccessStatus",
                "Entra · CA Insights workbook",
            ],
            wired=[
                "ca.yaml — sample CA policy targeting agent identities",
                "demo_agent/oauth.py — sets agent_id_override on token exchange",
            ],
            portals=[
                {"label": "Entra · Conditional Access", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_ConditionalAccess/ConditionalAccessBlade"},
                {"label": "Entra · CA What-If", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_ConditionalAccess/ConditionalAccessBlade/~/WhatIf"},
            ],
            queries=[
                {
                    "label": "Defender · CA decisions for this agent",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · CA decisions for this agent =====\n"
                        "// ConditionalAccessStatus is a top-level column on AADSpnSignInEventsBeta;\n"
                        "// no AdditionalFields parsing required.\n"
                        "AADSpnSignInEventsBeta\n"
                        f"| where ApplicationId == \"{PARENT_AGENT_APP}\" and Timestamp > ago(7d)\n"
                        "| summarize count() by ConditionalAccessStatus, ErrorCode, ResourceDisplayName\n"
                        "| sort by count_ desc"
                    ),
                },
            ],
        ),
        _f(
            id="idp",
            name="Identity Protection (agent-distinguishable)",
            category="Entra",
            pillar="Secure",
            status="configured",
            summary="User-risk signals on the served user surface to the agent at runtime via the SDK.",
            pitch="When the user becomes risky, the agent's next call inherits that risk score — surfaced in the control plane evidence log.",
            flow_in=[
                "Entra ID Protection assigns a risk score to the user",
                "Sidecar receives the risk envelope on token exchange",
                "Agent records risk on the run record",
            ],
            flow_out=[
                "AADUserRiskEvents — per-user risk",
                "Control plane: GET /api/runs/{id}/evidence shows risk per run",
            ],
            wired=[
                "demo_agent/observability.py — start_invoke_scope captures risk metadata",
                "demo_agent/web.py — /api/runs/{id}/evidence exposes the risk envelope",
            ],
            portals=[
                {"label": "Entra · Identity Protection", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/IdentityProtectionMenuBlade/~/Overview"},
                {"label": "Entra · Risky users", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/IdentityProtectionMenuBlade/~/RiskyUsers"},
            ],
            queries=[
                {
                    "label": "Defender · Identity risk on users served by this agent",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Identity risk on users served by this agent =====\n"
                        "// AADUserRiskEvents is a Sentinel table, NOT a Defender Advanced Hunting\n"
                        "// table. The equivalent in Defender XDR is IdentityInfo (latest snapshot\n"
                        "// per user). Cross-check the user_id on each agent run against the latest\n"
                        "// IdentityInfo risk score in the control plane evidence log.\n"
                        "IdentityInfo\n"
                        "| where Timestamp > ago(1d)\n"
                        "| where isnotempty(RiskLevel)\n"
                        "| summarize arg_max(Timestamp, *) by AccountObjectId\n"
                        "| project-reorder AccountUpn, AccountDisplayName, RiskLevel, RiskState, RiskLastUpdatedDateTime\n"
                        "| sort by RiskLevel asc, RiskLastUpdatedDateTime desc\n"
                        "| take 50"
                    ),
                },
            ],
        ),
        _f(
            id="sase",
            name="SASE for Agents (Global Secure Access)",
            category="Entra",
            pillar="Secure",
            status="roadmap",
            summary="ACA egress reachable from Global Secure Access; agent identity is GSA-eligible.",
            pitch="Same SSE stack you apply to employees, applied to the custom agent. Forward-compatible the day GSA agent enforcement GAs.",
            flow_in=[
                "Outbound HTTP from container egresses on known ACA IPs",
                "GSA client (when GA) tags traffic with agent identity",
            ],
            flow_out=[
                "GSA traffic logs (Entra · Global Secure Access · Traffic logs)",
                "GSA enriched fields in SigninLogs",
            ],
            wired=[
                "ACA workload pinned to known egress IPs (publishable to GSA)",
                "ESS_REQUIRE_GSA env-var toggle reserved in deploy/main.bicep",
            ],
            portals=[
                {"label": "Entra · Global Secure Access", "url": "https://entra.microsoft.com/#view/Microsoft_Azure_Network/NetworkMenuBlade/~/networkAccessOverview"},
            ],
            ga="Roadmap",
        ),
        _f(
            id="lifecycle-mgmt",
            name="Lifecycle Management for Agents",
            category="Entra",
            pillar="Govern",
            status="manual",
            summary="Lifecycle Workflows can target agent identities for joiner/mover/leaver flows.",
            pitch="Treat the agent like any other workload identity — joiner / leaver flows, expiry, owner-reassign.",
            flow_in=[
                "Per-user teammate creation triggers a workflow",
                "Manager change triggers a workflow",
            ],
            flow_out=[
                "Workflow execution log (Entra · Lifecycle workflows · Runs)",
            ],
            wired=[
                "Parent identity has Owner set to the deploying admin",
                "Per-user teammates expire with the served user's lifecycle",
            ],
            portals=[
                {"label": "Entra · Lifecycle workflows", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_ERM/DashboardBlade/~/elmlifecycleworkflows"},
            ],
        ),
        # ============================================================ Purview
        _f(
            id="dspm",
            name="DSPM for Agents",
            category="Purview",
            pillar="Secure",
            status="configured",
            summary="Tenant onboarded to DSPM-for-AI; agent emits prompts/responses with sensitivity classification.",
            pitch="Custom SDK agents are dark matter to DSPM by default. This one self-classifies every grounding hit.",
            flow_in=[
                "Agent SDK posts prompt + response to A365 control plane",
                "A365 forwards to Purview DSPM-for-AI for classification",
                "Custom SITs (4 registered) classify ESS-specific PII",
            ],
            flow_out=[
                "Purview · DSPM-for-AI · Reports",
                "AuditLog.UnifiedAuditLog (Workload=SecurityComplianceCenter, Operation=AIAppInteraction)",
            ],
            wired=[
                "demo_agent/purview.py — PurviewLabelClient",
                "demo_agent/scripts/setup-purview-dspm.ps1 — onboarding (steps 1-2 automated)",
                "Custom SITs: ESS Employee Id, ESS Workday Worker Id, ESS ServiceNow Sys Id, ESS Internal Ticket",
            ],
            portals=[
                {"label": "Purview · DSPM for AI", "url": "https://purview.microsoft.com/datasecurityandgovernance/copilotandaiapps/overview"},
                {"label": "Purview · Custom SITs", "url": "https://purview.microsoft.com/datalossprevention/sensitiveinfotypes"},
            ],
            queries=[
                {
                    "label": "Purview · Audit search (M365 UAL)",
                    "syntax": "powershell",
                    "portal": "purview-audit",
                    "code": (
                        "Connect-IPPSSession\n"
                        "Search-UnifiedAuditLog -StartDate (Get-Date).AddDays(-1) -EndDate (Get-Date) `\n"
                        "  -RecordType AIAppInteraction `\n"
                        f"  -ObjectIds '{PARENT_AGENT_APP}' -ResultSize 50 |\n"
                        "  Select-Object CreationDate, Operations, UserIds, AuditData"
                    ),
                },
            ],
        ),
        _f(
            id="irm",
            name="IRM for Agents",
            category="Purview",
            pillar="Secure",
            status="configured",
            summary="Insider Risk Management policies can target the agent identities via the audit pipe.",
            pitch="A compromised SDK agent is a high-impact insider risk. A365 makes the agent's actions reviewable.",
            flow_in=[
                "Every tool call emits agent.tool_call.observed",
                "Purview ingests via the SDK exporter",
                "IRM policy evaluates against agent identity",
            ],
            flow_out=[
                "Purview · Insider Risk Management · Alerts",
            ],
            wired=[
                "demo_agent/purview-policy.yaml — sample IRM target scope",
                "Every agent.tool_call.observed emits a Purview-routable event",
            ],
            portals=[
                {"label": "Purview · Insider Risk Management", "url": "https://purview.microsoft.com/insiderriskmgmt"},
            ],
        ),
        _f(
            id="label-hon",
            name="Label Honouring",
            category="Purview",
            pillar="Secure",
            status="active",
            summary="On every grounding result, agent calls Purview to fetch labels and gates the response.",
            pitch="Custom SDK agents ignore sensitivity labels unless you wire the SDK. This one does — verifiable from /api/identity.",
            flow_in=[
                "Tool result returned to agent",
                "purview.fetch_label_for queries Purview for the resource label",
                "Label compared against policy → pass / block / redact",
            ],
            flow_out=[
                "Purview · Activity Explorer · LabelApplied / LabelChanged",
                "Audit · LabelEnforcement events",
            ],
            wired=[
                "demo_agent/purview.py — fetch_label_for + is_blocked",
                "demo_agent/web.py — _call_tool_safe enforces label gates pre-response",
            ],
            portals=[
                {"label": "Purview · Information Protection", "url": "https://purview.microsoft.com/informationprotection"},
                {"label": "Purview · Activity Explorer", "url": "https://purview.microsoft.com/informationprotection/activityexplorer"},
            ],
            queries=[
                {
                    "label": "Purview · Activity Explorer (manual filter)",
                    "syntax": "url",
                    "portal": "purview-activity",
                    "code": (
                        "# Purview Activity Explorer does NOT accept ?app= or any filter\n"
                        "# parameter via URL — the previous link silently redirected to home.\n"
                        "# Open the canonical surface then apply the filter manually:\n"
                        "https://purview.microsoft.com/activityexplorer\n"
                        "# In the filter panel choose:\n"
                        f"#   Application : ESS Workday ServiceNow Hosted Demo Agent ({PARENT_AGENT_APP})\n"
                        "#   Activity   : LabelApplied / LabelChanged / SensitivityLabelEnforcement\n"
                        "#   Date       : Last 24h\n"
                    ),
                },
            ],
            ga="Sep 2026 (Foundry / 3P)",
        ),
        _f(
            id="label-inh",
            name="Label Inheritance",
            category="Purview",
            pillar="Secure",
            status="active",
            summary="When the agent writes (e.g. opens a ticket), it propagates the highest input label to the output.",
            pitch="Every artefact the SDK agent produces inherits the right label — no dev-team work needed.",
            flow_in=[
                "purview.propagate_labels computes max(input labels)",
                "Output artefact created with that label",
            ],
            flow_out=[
                "Purview · Activity Explorer · LabelApplied (Source=Agent)",
            ],
            wired=[
                "demo_agent/purview.py — propagate_labels()",
                "demo_agent/web.py — handle_runs records the resulting label on each step",
            ],
            portals=[
                {"label": "Purview · Sensitivity labels", "url": "https://purview.microsoft.com/informationprotection/sensitivitylabels"},
            ],
            ga="Sep 2026 (Foundry / 3P)",
        ),
        _f(
            id="dlp-ground",
            name="DLP for Grounding",
            category="Purview",
            pillar="Secure",
            status="configured",
            summary="DLP policies that target Generative AI apps cover this agent's grounding data via DSPM.",
            pitch="Even dev-owned RAG pipelines benefit from enforced tenant DLP once the agent is DSPM-registered.",
            flow_in=[
                "Agent registered as a Generative AI app in DSPM",
                "DLP policy with Generative AI app scope evaluates each prompt/response",
            ],
            flow_out=[
                "Purview · DLP · Policy match events",
                "DLPRuleMatch records in UnifiedAuditLog",
            ],
            wired=[
                "Agent identity surfaces in Purview Activity Explorer (Application=ESS Hosted Agent)",
            ],
            portals=[
                {"label": "Purview · DLP policies", "url": "https://purview.microsoft.com/datalossprevention/policiesv2"},
            ],
            queries=[
                {
                    "label": "Purview · DLP rule matches on this agent",
                    "syntax": "powershell",
                    "portal": "purview-audit",
                    "code": (
                        "Connect-IPPSSession\n"
                        "Search-UnifiedAuditLog -StartDate (Get-Date).AddDays(-1) -EndDate (Get-Date) `\n"
                        "  -Operations 'DLPRuleMatch' `\n"
                        f"  -FreeText '{PARENT_AGENT_APP}' -ResultSize 50"
                    ),
                },
            ],
            ga="Sep 2026 (Foundry / 3P)",
        ),
        _f(
            id="audit",
            name="Agent-Action Audit",
            category="Purview",
            pillar="Govern",
            status="active",
            summary="Every tool call, prompt, and response is emitted to the Purview audit log via the A365 SDK.",
            pitch="The audit pipe dev teams would have built themselves — included with A365 and already live.",
            flow_in=[
                "start_invoke_scope opens an OTEL span + posts AgentRunStarted",
                "ToolObservedEvent fires for each tool call",
                "start_inference_scope wraps every LLM call",
            ],
            flow_out=[
                "Purview · Audit search (RecordType=AIAppInteraction)",
                "Control plane · /api/runs/{id}/evidence",
            ],
            wired=[
                "demo_agent/observability.py — start_invoke_scope, start_inference_scope, ToolObservedEvent",
                "demo_agent/web.py — _publish_run_event mirrors to control-plane evidence log",
            ],
            portals=[
                {"label": "Purview · Audit search", "url": purview_audit},
                {"label": "Purview · Activity Explorer", "url": "https://purview.microsoft.com/informationprotection/activityexplorer"},
            ],
            queries=[
                {
                    "label": "Purview · UAL search for this agent (24h)",
                    "syntax": "powershell",
                    "portal": "purview-audit",
                    "code": (
                        "Connect-IPPSSession\n"
                        "Search-UnifiedAuditLog -StartDate (Get-Date).AddHours(-24) -EndDate (Get-Date) `\n"
                        "  -RecordType AIAppInteraction `\n"
                        f"  -FreeText '{PARENT_AGENT_APP}' -ResultSize 100 |\n"
                        "  Select-Object CreationDate, Operations, UserIds, AuditData |\n"
                        "  Format-Table -AutoSize"
                    ),
                },
                {
                    "label": "Defender · Cross-correlate audit + sign-ins",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Cross-correlate audit + sign-ins =====\n"
                        "// AADSpnSignInEventsBeta is the table that carries our agent's outbound\n"
                        "// sign-ins. CloudAppEvents does NOT have an AccountUpn column and is only\n"
                        "// populated when Defender for Cloud Apps proxies the app — not the case\n"
                        "// for SDK agents. Filter by ApplicationId to scope to this agent.\n"
                        "AADSpnSignInEventsBeta\n"
                        f"| where ApplicationId == \"{PARENT_AGENT_APP}\" and Timestamp > ago(24h)\n"
                        "| project-reorder Timestamp, Application, ResourceDisplayName, IPAddress, ErrorCode, ConditionalAccessStatus, CorrelationId\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                _byo_mcp_query("Defender · BYO MCP Tooling Gateway invocations"),
            ],
        ),
        _f(
            id="comp-mgr",
            name="Compliance Manager (agent templates)",
            category="Purview",
            pillar="Govern",
            status="manual",
            summary="Compliance Manager has an Agent 365 template family; operator binds the agent to the relevant assessment.",
            pitch="Custom agents get their own line in Compliance Manager — no black boxes.",
            flow_in=[
                "Operator imports the Agent 365 Compliance template",
                "Assessment scope set to this agent's identity",
            ],
            flow_out=[
                "Compliance Manager · Score + recommended actions",
            ],
            wired=[
                "Manifest publishes the agent's compliance metadata used by the template",
            ],
            portals=[
                {"label": "Purview · Compliance Manager", "url": "https://purview.microsoft.com/compliancemanager/assessments"},
            ],
            ga="Jul 2026",
        ),
        # =========================================================== Defender
        _f(
            id="sec-posture",
            name="Agent Security Posture Management (ASPM for AI)",
            category="Defender",
            pillar="Secure",
            status="configured",
            summary="Defender for Cloud Apps discovers the agent via the A365 control-plane traffic fingerprint.",
            pitch="A365 plus Defender = continuous posture grade for *your* SDK agent, not just Copilot.",
            flow_in=[
                "Agent egress to agent365.svc.cloud.microsoft fingerprinted by MDA",
                "Posture rules evaluate identity + endpoint hygiene",
            ],
            flow_out=[
                "Defender · Cloud apps · Discovery · AI agents and assets",
                "Defender · Security posture for AI",
            ],
            wired=[
                "Outbound to agent365.svc.cloud.microsoft is discoverable by MDA",
                "demo_agent/scripts/register-defender-ai-agent.ps1 — automates MI grants + portal flow",
            ],
            portals=[
                {"label": "Defender · Security posture for AI", "url": "https://security.microsoft.com/securityposture"},
                {"label": "Defender · Discover AI agents", "url": "https://security.microsoft.com/discoveryReports"},
            ],
        ),
        _f(
            id="threat-det",
            name="Threat Detection",
            category="Defender",
            pillar="Secure",
            status="configured",
            summary="AIAgentsInfo + BehaviorEntities + AlertInfo tables ingest this agent's identity post-onboarding.",
            pitch="The agent's misbehaviour shows up in the same XDR experience your SOC already uses.",
            flow_in=[
                "Sign-ins → AADSpnSignInEventsBeta (automatic)",
                "Agent runs → CloudAppEvents (via A365 SDK)",
                "Behavior anomalies → BehaviorEntities (Defender ML)",
            ],
            flow_out=[
                "AlertInfo / IncidentInfo when ML flags anomalies",
                "Custom detection rules created from the playbook",
            ],
            wired=[
                "Per-identity sign-ins emit to AADSpnSignInEventsBeta automatically",
                "Custom detection rules documented in DEFENDER_HUNTING.md",
            ],
            portals=[
                {"label": "Defender · Advanced Hunting", "url": advhunt},
                {"label": "Defender · AI Agents inventory", "url": "https://security.microsoft.com/securitysettings/agents"},
            ],
            queries=[
                {
                    "label": "Defender · Is the agent registered?",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Is the agent registered? =====\n"
                        "// PREVIEW table. AIAgentsInfo ships with Defender for AI; if it is not\n"
                        "// enabled in your tenant the query returns 'Failed to resolve table\n"
                        "// or column expression' — fall back to the servicePrincipals Graph\n"
                        "// query in the Graph API card to confirm registration. Column names\n"
                        "// below are best-effort from public preview docs; adjust if the\n"
                        "// schema reference shows different names.\n"
                        "AIAgentsInfo\n"
                        f"| where AgentId == \"{PARENT_AGENT_APP}\" or AgentName has \"ESS\"\n"
                        "| project-reorder Timestamp, AgentId, AgentName, AgentStatus, AgentType\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                {
                    "label": "Defender · Behavior anomalies referencing this agent",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Behavior anomalies referencing this agent =====\n"
                        "// BehaviorEntities + BehaviorInfo are GA Defender tables but their\n"
                        "// EntityType taxonomy does NOT include 'AIAgent' yet. The reliable\n"
                        "// way to find rows tied to our agent is to match the AppId anywhere\n"
                        "// in EntityId, EntityName, or AdditionalFields, then join behaviour\n"
                        "// info. Returns 0 rows in tenants with no behaviour anomalies.\n"
                        "BehaviorEntities\n"
                        f"| where EntityId == \"{PARENT_AGENT_APP}\"\n"
                        f"    or EntityName has \"ESS\"\n"
                        f"    or AdditionalFields has \"{PARENT_AGENT_APP}\"\n"
                        "| join kind=inner (BehaviorInfo) on BehaviorId\n"
                        "| project-reorder Timestamp, EntityName, EntityType, ActionType, Severity, Description, Categories, DetectionSource\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                _byo_mcp_query("Defender · BYO MCP Tooling Gateway invocations"),
            ],
            docs=["demo_agent/docs/DEFENDER_HUNTING.md"],
        ),
        _f(
            id="rt-protect",
            name="Real-time Threat Protection",
            category="Defender",
            pillar="Secure",
            status="active",
            summary="Server-side tool deny-list blocks denied tools instantly; mirrored to Defender via audit.",
            pitch="A365's runtime hook plus Defender's response actions give defence in depth without sacrificing latency.",
            flow_in=[
                "Operator POSTs to /api/governance/tool-denylist",
                "Every tool call passes through _call_tool_safe enforcement",
                "Denied calls emit a Purview event + Defender custom-detection alert",
            ],
            flow_out=[
                "AlertInfo / Custom detection rule matches",
                "Control plane · ToolDenied evidence entries",
            ],
            wired=[
                "demo_agent/web.py — _call_tool_safe enforces governance.tool_denylist",
                "/api/governance/tool-denylist accepts updates without redeploy",
            ],
            portals=[
                {"label": "Defender · Custom detection rules", "url": "https://security.microsoft.com/customDetections"},
                {"label": "Control plane · Governance", "url": f"https://{AGENT_FQDN}/control-plane"},
            ],
            queries=[
                {
                    "label": "Defender · Detection rule template (destructive tool block)",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Detection rule template (destructive tool block) =====\n"
                        "// TEMPLATE — not expected to return rows until a custom detection rule\n"
                        "// emits 'AgentToolDenied' events into a custom table or until Defender\n"
                        "// for AI starts ingesting our /api/governance/tool-denylist signal.\n"
                        "// Today our agent's tool-deny enforcement is visible at:\n"
                        "//   GET https://<agent-fqdn>/api/runs/<id>/evidence\n"
                        "// Use this query as the starting point for a Custom Detection Rule\n"
                        "// when you wire your own emission into CustomTable_CL / CloudAppEvents.\n"
                        "AADSpnSignInEventsBeta\n"
                        f"| where ApplicationId == \"{PARENT_AGENT_APP}\" and Timestamp > ago(24h)\n"
                        "| where ErrorCode != 0\n"
                        "| project-reorder Timestamp, Application, ResourceDisplayName, ErrorCode, FailureReason, IPAddress\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                _byo_mcp_query("Defender · BYO MCP Tooling Gateway invocations"),
            ],
        ),
        _f(
            id="hunting",
            name="Threat Hunting & Investigation",
            category="Defender",
            pillar="Secure",
            status="active",
            summary="Pre-built KQL playbook ships in the control plane and as a Markdown doc.",
            pitch="Custom SDK agents are normally invisible to your SOC. This one ships its own hunting playbook.",
            flow_in=[
                "Every run/tool/inference emits a CloudAppEvents row",
                "Sign-ins emit AADSpnSignInEventsBeta",
                "DSPM events emit to CloudAppEvents.AppCategory='Generative AI'",
            ],
            flow_out=[
                "Defender · Advanced Hunting · saved queries",
                "Defender · Custom detection rules",
            ],
            wired=[
                "demo_agent/docs/DEFENDER_HUNTING.md — full KQL playbook",
                "Control plane surfaces card → Defender hunting deep links",
            ],
            portals=[
                {"label": "Defender · Advanced Hunting", "url": advhunt},
            ],
            queries=[
                {
                    "label": "Defender · 7-day sign-in activity summary",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · 7-day sign-in activity summary =====\n"
                        "// Counts sign-ins by error code so success / CA-block / failure ratios\n"
                        "// are visible. The previous CloudAppEvents version did not return rows\n"
                        "// because the agent is not proxied by Defender for Cloud Apps.\n"
                        "AADSpnSignInEventsBeta\n"
                        "| where Timestamp > ago(7d)\n"
                        f"| where ApplicationId == \"{PARENT_AGENT_APP}\"\n"
                        "| summarize Count = count() by bin(Timestamp, 1d), ResourceDisplayName, tostring(ErrorCode), ConditionalAccessStatus\n"
                        "| sort by Timestamp asc"
                    ),
                },
                {
                    "label": "Defender · Alerts referencing this agent",
                    "syntax": "kql",
                    "portal": "defender-hunting",
                    "code": (
                        "// ===== ESS Agent 365 · Alerts referencing this agent =====\n"
                        "// AlertEvidence carries one row per evidence artefact on an alert. For\n"
                        "// an OAuth / service-principal agent, the matching column is\n"
                        "// OAuthApplicationId (and sometimes ApplicationId). AccountObjectId is\n"
                        "// the USER's AAD oid — it never holds an app GUID. Returns 0 rows in\n"
                        "// tenants where no alert has yet referenced this agent.\n"
                        "AlertEvidence\n"
                        "| where Timestamp > ago(30d)\n"
                        f"| where OAuthApplicationId == \"{PARENT_AGENT_APP}\"\n"
                        f"    or ApplicationId == \"{PARENT_AGENT_APP}\"\n"
                        f"    or AdditionalFields has \"{PARENT_AGENT_APP}\"\n"
                        "| join kind=inner (AlertInfo) on AlertId\n"
                        "| project-reorder Timestamp, Title, Severity, Category, AttackTechniques, ServiceSource, DetectionSource, EntityType\n"
                        "| sort by Timestamp desc\n"
                        "| take 50"
                    ),
                },
                _byo_mcp_query("Defender · BYO MCP Tooling Gateway invocations"),
            ],
            docs=["demo_agent/docs/DEFENDER_HUNTING.md"],
        ),
        # ===================================================== M365 Admin / MAC
        _f(
            id="a365-sdk",
            name="Agent 365 SDK",
            category="M365 Admin Center",
            pillar="Govern",
            status="active",
            summary="Agent boots the A365 SDK on startup, registers, and emits OTEL traces + Purview events on every run.",
            pitch="The bedrock — once the SDK is in, every other A365 capability lights up automatically.",
            flow_in=[
                "Container boot → observability init",
                "Sidecar token exchange supplies AgentIdentity token",
                "SDK registers agent with A365 fabric on first invoke",
            ],
            flow_out=[
                "OTEL spans to agent365.svc.cloud.microsoft",
                "Purview events to the M365 audit pipe",
                "MAC registry entry for this agent",
            ],
            wired=[
                "demo_agent/observability.py — A365 SDK init + token via managed identity",
                "/api/identity.observability.sdkConfigured == true at runtime",
            ],
            portals=[
                {"label": "M365 Admin · Agent registry", "url": "https://admin.microsoft.com/Adminportal/Home#/agents"},
                {"label": "Control plane · /api/identity", "url": f"https://{AGENT_FQDN}/api/identity"},
            ],
        ),
        _f(
            id="agent-registry",
            name="Agent Registry",
            category="M365 Admin Center",
            pillar="Observe",
            status="active",
            summary="Agent advertises its scenarios, tools, owner, and endpoint to MAC.",
            pitch="Your dev-built agent appears in M365 Admin alongside Copilot — single inventory.",
            flow_in=[
                "ToolingManifest.json published to MAC at deploy time",
                "Per-user instance template published via republish-ai-teammate-template.ps1",
            ],
            flow_out=[
                "MAC · Agents inventory row",
                "MAC · Agent details blade",
            ],
            wired=[
                "demo_agent/ToolingManifest.json — published to MAC",
                "manifest/agenticUserTemplateManifest.json — per-user instance template",
            ],
            portals=[
                {"label": "M365 Admin · Agents", "url": "https://admin.microsoft.com/Adminportal/Home#/agents"},
            ],
        ),
        _f(
            id="agent-map",
            name="Agent Map",
            category="M365 Admin Center",
            pillar="Observe",
            status="active",
            summary="MAC Agent Map renders dependencies (Workday, ServiceNow, Graph, Foundry) from the manifest.",
            pitch="Visualise how the custom agent fits into the wider agentic ecosystem.",
            flow_in=[
                "ToolingManifest declares MCP servers + downstream APIs",
                "Foundry project id surfaced from /api/identity.foundry",
            ],
            flow_out=[
                "MAC · Agent Map graph render",
            ],
            wired=[
                "ToolingManifest.json — declares MCP servers and downstream APIs",
                "Foundry project id surfaced via /api/identity.foundry",
            ],
            portals=[
                {"label": "M365 Admin · Agent Map", "url": "https://admin.microsoft.com/Adminportal/Home#/agents/map"},
            ],
        ),
        _f(
            id="registry-sync",
            name="Registry Sync",
            category="M365 Admin Center",
            pillar="Observe",
            status="configured",
            summary="Manifest republish keeps the MAC inventory in sync after each agent revision.",
            pitch="Ship a new agent revision → MAC reflects it automatically.",
            flow_in=[
                "republish-ai-teammate-template.ps1 invoked at deploy time",
            ],
            flow_out=[
                "MAC · Agents · LastModified updated",
            ],
            wired=[
                "demo_agent/scripts/republish-ai-teammate-template.ps1",
            ],
            portals=[
                {"label": "M365 Admin · Agents", "url": "https://admin.microsoft.com/Adminportal/Home#/agents"},
            ],
        ),
        _f(
            id="graph-api",
            name="Graph API for Agent Management",
            category="M365 Admin Center",
            pillar="Observe",
            status="active",
            summary="Agent consumes the Graph beta agent-management surfaces (identity, AgenticUserAuthorization).",
            pitch="A365 exposes a coherent Graph API for agent admins — this agent both consumes and is observable via it.",
            flow_in=[
                "Sidecar exchanges MSI for AgentIdentity token via Graph",
                "Agent calls Graph beta endpoints for per-user teammate metadata",
            ],
            flow_out=[
                "Graph audit log entries against the agent app",
            ],
            wired=[
                "demo_agent/identity.py — AgenticUserAuthorization runtime",
                "demo_agent/scripts/oauth-bootstrap.py — Graph beta endpoint usage",
            ],
            portals=[
                {"label": "Graph Explorer", "url": "https://developer.microsoft.com/graph/graph-explorer"},
            ],
            queries=[
                {
                    "label": "Graph Explorer · Get parent agent service principal",
                    "syntax": "url",
                    "portal": "graph-explorer",
                    "code": (
                        f"https://developer.microsoft.com/graph/graph-explorer?request=servicePrincipals(appId%3D%27{PARENT_AGENT_APP}%27)&method=GET&version=v1.0"
                    ),
                },
            ],
        ),
        _f(
            id="tool-ctrl",
            name="Tool Controls",
            category="M365 Admin Center",
            pillar="Govern",
            status="active",
            summary="Operator-editable tool deny-list enforced server-side on every invocation.",
            pitch="A365's MAC tool controls + your in-agent policy give administrators a kill switch they trust.",
            flow_in=[
                "Operator POSTs to /api/governance/tool-denylist",
                "Policy stored server-side and consulted on every _call_tool_safe",
            ],
            flow_out=[
                "Control plane · Governance card · Active deny-list",
                "ToolDenied evidence entries on each run",
            ],
            wired=[
                "demo_agent/web.py — handle_governance_denylist + _call_tool_safe enforcement",
                "/api/governance + /api/governance/tool-denylist endpoints",
            ],
            portals=[
                {"label": "M365 Admin · Tool controls", "url": "https://admin.microsoft.com/Adminportal/Home#/agents/policies"},
                {"label": "Control plane · Governance", "url": f"https://{AGENT_FQDN}/control-plane"},
            ],
        ),
        _f(
            id="policy-tpl",
            name="Policy Templates",
            category="M365 Admin Center",
            pillar="Govern",
            status="configured",
            summary="The agent ships default policy templates that MAC operators can override.",
            pitch="Sensible defaults shipped by the dev team, override-able by admins — exactly the A365 model.",
            flow_in=[
                "purview-policy.yaml + ca.yaml shipped with each revision",
                "Operator imports / overrides as needed",
            ],
            flow_out=[
                "Active CA + Purview policy in the tenant",
            ],
            wired=[
                "demo_agent/purview-policy.yaml — default Purview policy template",
                "ca.yaml — default CA template",
            ],
            portals=[
                {"label": "M365 Admin · Policies", "url": "https://admin.microsoft.com/Adminportal/Home#/agents/policies"},
            ],
        ),
        _f(
            id="admin-actions",
            name="Admin Agent Governance Actions",
            category="M365 Admin Center",
            pillar="Govern",
            status="active",
            summary="Disable / re-enable / revoke-consent / kill-run wired in the control plane and replicated in MAC.",
            pitch="Admins can intervene without paging the dev team.",
            flow_in=[
                "Operator hits /api/runs/{id}/cancel or /api/governance/*",
                "Server flips enabled flag or aborts in-flight runs",
            ],
            flow_out=[
                "Run record · status=Cancelled",
                "/api/identity.enabled reflects the kill switch",
            ],
            wired=[
                "demo_agent/web.py — /api/runs/{id}/cancel, /api/governance/*",
                "/api/identity.enabled toggle",
            ],
            portals=[
                {"label": "M365 Admin · Agents", "url": "https://admin.microsoft.com/Adminportal/Home#/agents"},
                {"label": "Control plane · Governance", "url": f"https://{AGENT_FQDN}/control-plane"},
            ],
        ),
        _f(
            id="rbac",
            name="AI Admin / AI Reader RBAC",
            category="M365 Admin Center",
            pillar="Govern",
            status="manual",
            summary="Manifest declares the RBAC roles required to admin/read this agent; operator assigns.",
            pitch="Least-privilege agent admin out of the box.",
            flow_in=[
                "ToolingManifest declares required roles",
                "Operator assigns AI Admin / AI Reader to ops staff",
            ],
            flow_out=[
                "Entra · Role assignments visible per user",
            ],
            wired=[
                "ToolingManifest.json declares required RBAC roles",
            ],
            portals=[
                {"label": "Entra · Roles and admins", "url": "https://entra.microsoft.com/#view/Microsoft_AAD_IAM/RolesManagementMenuBlade/~/AllRoles"},
            ],
        ),
        # ============================================================ Intune
        _f(
            id="agent-runtime-policy",
            name="Policy-Controlled Agent Runtime (W365 for Agents)",
            category="Intune",
            pillar="Secure",
            status="roadmap",
            summary="ACA host is policy-targetable; W365-for-Agents will run the same image under Intune.",
            pitch="Same hardening surface Intune gives a managed device — applied to the agent's runtime.",
            flow_in=[
                "Dockerfile produces a minimal image (non-root, no shell on PATH)",
                "Image pinned in deploy/main.bicep",
            ],
            flow_out=[
                "Intune · Endpoint security posture (when GA)",
            ],
            wired=[
                "deploy/main.bicep — base image pinned and minimal",
                "Dockerfile — runs as non-root, no shell on PATH after build",
            ],
            portals=[
                {"label": "Intune · Endpoint security", "url": "https://intune.microsoft.com/#view/Microsoft_Intune_Workflows/SecurityManagementMenu/~/0"},
            ],
            ga="Roadmap",
        ),
    ]


def status_summary(features: list[dict[str, Any]] | None = None) -> dict[str, int]:
    """Return counts per status value, ordered by STATUS_ORDER."""
    feats = features or feature_catalog()
    counts = {s: 0 for s in STATUS_ORDER}
    for f in feats:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return counts


def category_summary(features: list[dict[str, Any]] | None = None) -> dict[str, dict[str, int]]:
    """Return per-category status counts."""
    feats = features or feature_catalog()
    out: dict[str, dict[str, int]] = {}
    for f in feats:
        bucket = out.setdefault(f["category"], {s: 0 for s in STATUS_ORDER})
        bucket[f["status"]] = bucket.get(f["status"], 0) + 1
    return out
