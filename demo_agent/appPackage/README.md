# Group Functions Autopilot — Teams package

This package is separate from the repository's declarative agent and the A365
agentic-user template in [../manifest](../manifest/README.md).

The canonical sources are:

- [manifest.json](manifest.json): Group Functions Autopilot name, developer,
  description, bot scopes and authenticated control-plane tab.
- [color.png](color.png): new 192 × 192 compass/navigation icon.
- [outline.png](outline.png): new 32 × 32 white-on-transparent Teams outline.

This is a **source template**, not a ready-to-upload package. Resolve
`TEAMS_APP_ID`, `BOT_ID` and `AGENT_DOMAIN` from the new Caldova registrations
and deployed host before packaging. Do not fabricate IDs or use retired
environment files. The obsolete development environment and its ZIP were deleted.

The Toolkit output name is `group-functions-autopilot.<environment>.zip`.
Packaging is not catalog submission; submission still requires tenant approval.

Icon source and repeatable rendering are documented in
[../docs/AUTOPILOT_BRANDING.md](../docs/AUTOPILOT_BRANDING.md).