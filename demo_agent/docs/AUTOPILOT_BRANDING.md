# Group Functions Autopilot branding

The product, app listing, developer display name and user-facing host title are
**Group Functions Autopilot**. The original artwork is a white navigation pointer
inside a three-node compass arc on a deep-rose tile. It contains no wordmark or
legacy acronym and stays legible at Teams icon sizes.

## Sources

| Surface | Manifest / artwork |
| --- | --- |
| A365 application and agentic-user template | [../manifest/manifest.json](../manifest/manifest.json), [../manifest/agenticUserTemplateManifest.json](../manifest/agenticUserTemplateManifest.json) |
| Teams bot and control-plane package | [../appPackage/manifest.json](../appPackage/manifest.json) |
| Vector icon, favicon and web header | [../static/autopilot-icon.svg](../static/autopilot-icon.svg) |
| Color icon: 192 × 192, opaque | [../manifest/color.png](../manifest/color.png), [../appPackage/color.png](../appPackage/color.png) |
| Outline icon: 32 × 32, white + alpha | [../manifest/outline.png](../manifest/outline.png), [../appPackage/outline.png](../appPackage/outline.png) |
| Reproducible artwork generator | [../scripts/render_autopilot_icons.py](../scripts/render_autopilot_icons.py) |

The renderer uses build-only [../requirements-branding.txt](../requirements-branding.txt),
not a runtime dependency. The color/outline pairs must be identical in both
package directories. Both web surfaces load the same SVG through one exact,
public static route; operational APIs remain authenticated.

## Publication order

1. Prepare and review the branding and manifests now.
2. Deploy and verify the HTTPS host, control-plane SSO and A365 messaging endpoint.
3. Resolve the remaining manifest variables from the real new registrations.
4. Build the final A365 package from the isolated Caldova CLI configuration and
   validate the archive's names, URLs, IDs and PNGs. Build the Teams package from
   its own source manifest with the same artwork.
5. Submit and obtain tenant approval, create the intended agent instance, and
   execute the live compliance UAT journey. A generated ZIP is not proof of UAT.

## Retired artifacts

Obsolete local credentials, configuration, development ZIPs and rendered
manifests from the expired tenant were removed. Shared backend code and the live
Caldova MCP apps remain. Internal compatibility environment-variable names and
legacy browser-storage cleanup keys are not product branding and are not renamed
blindly. Operator portal links now derive from this deployment's configuration,
not hardcoded retired tenant IDs.