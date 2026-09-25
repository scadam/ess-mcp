# Group Functions Autopilot — Agent 365 package

- [manifest.json](manifest.json) is the canonical A365 application manifest.
- [agenticUserTemplateManifest.json](agenticUserTemplateManifest.json) is the
  activity-protocol template associated with the real Caldova blueprint.
- [color.png](color.png) and [outline.png](outline.png) are the new Autopilot artwork.

The blueprint ID is `77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde` ("Group Functions Autopilot v2").
The A365 CLI always sets the package `id` to the blueprint ID, so a new admin-center
title needs a new blueprint. The first blueprint, `7b3bf810-61f1-46f3-8e9c-89a61a761037`,
is retired: its uploaded title used the wrong policy template and can't be changed.
The template ID is new for v2, so it can't collide with the retired title.
The v2 CLI working directory is the session's `a365-v2` folder. Its publish project
renders this manifest with the live host and the title "Group Functions Autopilot v2".

**Draft until deployment:** `${{AGENT_DOMAIN}}` deliberately remains unresolved.
Render it from the verified HTTPS host after endpoint registration, then run
`a365 publish --aiteammate` from the isolated Caldova CLI working directory.
Its `deploymentProjectPath` now points to the parent application folder, so it
uses this manifest and these icons. Do not run publish from a directory with an
unrelated A365 configuration.

`a365 publish` prepares the ZIP. It is not host deployment, org-catalog approval,
agentic mailbox provisioning or evidence that the compliance workflow works.
The final package must be rechecked for exact names, icons, IDs and live URLs
before submission. Old ZIPs and old-tenant configuration have been deleted.