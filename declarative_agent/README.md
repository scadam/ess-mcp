# Overview of the Declarative Agent template

With the declarative agent, you can build a custom version of Copilot that can be used for specific scenarios, such as for specialized knowledge, implementing specific processes, or simply to save time by reusing a set of AI prompts. For example, a grocery shopping Copilot declarative agent can be used to create a grocery list based on a meal plan that you send to Copilot.

## Caldova MCP endpoints and authentication

All seven plugin definitions point to the new Caldova MCP endpoints. Endpoint changes do not register OAuth connections, enable server-side credential fallback, or change which actions the agent includes.

**Bearer-first demo behavior:** Workday, Salesforce, and ServiceNow now declare `None` and obtain server-side tokens from Key Vault-backed credentials when no bearer is supplied. If the client supplies a bearer token, that token is used instead; a rejected caller token never falls back to the stored account. All three paths were verified with read-only live calls. No-header calls use the stored account's permissions, not the user's identity.

**Jira remains different:** its plugin still declares `None` but the server requires a consented user bearer token. Configure an actual new-tenant Jira OAuth connection before enabling that action; no reference ID or credentials are fabricated. ServiceNow's obsolete old-tenant reference was removed for fallback mode.

See the shared [authentication matrix and verified flows](../cowork/AUTHENTICATION.md). The agent's existing action selection, Graph connector, IDs, and version are preserved. Existing package copies can receive endpoint-only refreshes; this is not a full package regeneration, OAuth registration, or tenant publication.

## Caldova ATK packaging

- Use ATK **1.1.17** for this agent. ATK 1.1.12 rejects the valid `EmailActions` and `MeetingActions` capabilities in its local parser.
- Provision using the isolated [env/.env.caldova](env/.env.caldova) environment; the existing dev registration belongs to the previous tenant and must not be reused.
- Salesforce uses live MCP discovery. An explicit empty `mcp_tool_description.tools` list disables that discovery and is rejected by Microsoft 365.
- Microsoft 365 rejects `sensitivity_label` when neither embedded knowledge nor agent skills are declared. [prepare_caldova_package.ps1](prepare_caldova_package.ps1) conditionally omits only that field from the **Caldova ZIP**, retaining it in the authored [appPackage/declarativeAgent.json](appPackage/declarativeAgent.json). The label is retained automatically if embedded content is added. Other environments are not adapted.
- After provisioning, publish the verified [appPackage/build/appPackage.caldova.zip](appPackage/build/appPackage.caldova.zip) with ATK's explicit `--package-file` option. In the tested CLI, omitting that option rebuilds the unadapted source rather than running the custom publish lifecycle steps.
- An ATK publish success is an **organization-catalog submission**, not admin approval. Review and approve it in [Teams Admin Center](https://admin.teams.microsoft.com/policies/manage-apps).

## Agent skills (v1.0.1)

- Seven skills live in [appPackage/skills](appPackage/skills), one folder per skill with its `SKILL.md` plus any `references/` and `scripts/`. [appPackage/declarativeAgent.json](appPackage/declarativeAgent.json) lists them under `agent_skills` (maximum 8), which needs declarative agent manifest **v1.9**: the published v1.8 schema only allows a fixed list of root properties, so a v1.8 package with `agent_skills` is rejected on upload.
- During the preview, provision skill agents with ATK (`atk provision --env caldova`, then `atk publish` for the organization catalog) rather than uploading the ZIP by hand.
- ATK only copies skill folders into the ZIP when `TEAMSFX_AGENT_SKILLS=true`. Build with ATK **1.1.17**: `$env:TEAMSFX_AGENT_SKILLS='true'; npx @microsoft/m365agentstoolkit-cli@1.1.17 package --env caldova`, then run [prepare_caldova_package.ps1](prepare_caldova_package.ps1).
- Keep `name:` and `description:` on single lines in each `SKILL.md`: ATK's frontmatter check reads one `key: value` per line, and `name` must match the folder.
- Skill scripts use only the Python standard library; they run in a sandbox without network access and can't call the MCP servers.
- With skills declared, the platform accepts the agent's `sensitivity_label`, so the Caldova ZIP keeps it.

## Get started with the template

> **Prerequisites**
>
> To run this app template in your local dev machine, you will need:
>
> - [Node.js](https://nodejs.org/), supported versions: 18, 20, 22
> - A [Microsoft 365 account for development](https://docs.microsoft.com/microsoftteams/platform/toolkit/accounts).
> - [Microsoft 365 Agents Toolkit Visual Studio Code Extension](https://aka.ms/teams-toolkit) version 5.0.0 and higher or [Microsoft 365 Agents Toolkit CLI](https://aka.ms/teamsfx-toolkit-cli)
> - [Microsoft 365 Copilot license](https://learn.microsoft.com/microsoft-365-copilot/extensibility/prerequisites#prerequisites)

![image](https://github.com/user-attachments/assets/51a221bb-a2c6-4dbf-8009-d2aa20a1638f)

1. First, select the Microsoft 365 Agents Toolkit icon on the left in the VS Code toolbar.
2. In the Account section, sign in with your [Microsoft 365 account](https://docs.microsoft.com/microsoftteams/platform/toolkit/accounts) if you haven't already.
3. Select `Preview Local in Copilot (Edge)` or `Preview Local in Copilot (Chrome)` from the launch configuration dropdown.
4. Select your declarative agent from the `Copilot` app.
5. Ask a question to your declarative agent and it should respond based on the instructions provided.

## What's included in the template

| Folder       | Contents                                                                                 |
| ------------ | ---------------------------------------------------------------------------------------- |
| `.vscode`    | VSCode files for debugging                                                               |
| `appPackage` | Templates for the application manifest, the GPT manifest and the API specification |
| `env`        | Environment files                                                                        |

The following files can be customized and demonstrate an example implementation to get you started.

| File                               | Contents                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| `appPackage/declarativeAgent.json` | Define the behaviour and configurations of the declarative agent.            |
| `appPackage/manifest.json`         | application manifest that defines metadata for your declarative agent. |

The following are Microsoft 365 Agents Toolkit specific project files. You can [visit a complete guide on Github](https://github.com/OfficeDev/TeamsFx/wiki/Teams-Toolkit-Visual-Studio-Code-v5-Guide#overview) to understand how Microsoft 365 Agents Toolkit works.

| File           | Contents                                                                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `m365agents.yml` | This is the main Microsoft 365 Agents Toolkit project file. The project file defines two primary things: Properties and configuration Stage definitions. |

## Extend the template

- [Add conversation starters](https://learn.microsoft.com/microsoft-365-copilot/extensibility/build-declarative-agents?tabs=ttk&tutorial-step=3): Conversation starters are hints that are displayed to the user to demonstrate how they can get started using the declarative agent.
- [Add web content](https://learn.microsoft.com/microsoft-365-copilot/extensibility/build-declarative-agents?tabs=ttk&tutorial-step=4) for the ability to search web information.
- [Add OneDrive and SharePoint content](https://learn.microsoft.com/microsoft-365-copilot/extensibility/build-declarative-agents?tabs=ttk&tutorial-step=5) as grounding knowledge for the agent.
- [Add Microsoft Copilot connectors content](https://learn.microsoft.com/microsoft-365-copilot/extensibility/build-declarative-agents?tabs=ttk&tutorial-step=6) to ground agent with enterprise knowledge.
- [Add API plugins](https://learn.microsoft.com/microsoft-365-copilot/extensibility/build-declarative-agents?tabs=ttk&tutorial-step=7) for agent to interact with REST APIs.

## Addition information and references

- [Declarative agents for Microsoft 365](https://aka.ms/teams-toolkit-declarative-agent)
