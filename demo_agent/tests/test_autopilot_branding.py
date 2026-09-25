"""Offline branding guards; these do not replace rendered package validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_agent.identity import AgentIdentityContext
from demo_agent.scripts.render_autopilot_icons import render, verify


ROOT = Path(__file__).resolve().parents[1]
NAME = "Group Functions Autopilot"
BLUEPRINT = "77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde"
OLD = re.compile(r"\bESS\b|wittysand-460bf1d9|M365CPI81302533|8030d928-e557-4a4c-ae1e-95c1c4125eaa|3f028e66-44cf-4cee-81ee-03ade7717884", re.I)


class AutopilotBrandingTests(unittest.TestCase):
    def test_canonical_manifests_have_only_autopilot_branding(self):
        for folder in (ROOT / "manifest", ROOT / "appPackage"):
            text = (folder / "manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(text)
            with self.subTest(folder=folder.name):
                self.assertEqual(manifest["name"], {"short": NAME, "full": NAME})
                self.assertEqual(manifest["developer"]["name"], NAME)
                self.assertEqual(manifest["icons"], {"color": "color.png", "outline": "outline.png"})
                self.assertEqual(manifest["accentColor"], "#B11F4B")
                self.assertLessEqual(len(manifest["description"]["short"]), 80)
                self.assertIsNone(OLD.search(text))
                # Unresolved host is deliberate until live endpoint verification.
                self.assertIn("${{AGENT_DOMAIN}}", text)

    def test_a365_template_binds_only_the_real_caldova_blueprint(self):
        manifest = json.loads((ROOT / "manifest/manifest.json").read_text(encoding="utf-8"))
        template_text = (ROOT / "manifest/agenticUserTemplateManifest.json").read_text(encoding="utf-8")
        template = json.loads(template_text)
        self.assertEqual(manifest["id"], BLUEPRINT)
        self.assertEqual(template["agentIdentityBlueprintId"], BLUEPRINT)
        self.assertEqual(manifest["agenticUserTemplates"][0]["id"], template["id"])
        self.assertEqual(template["communicationProtocol"], "activityProtocol")
        self.assertIsNone(OLD.search(template_text))

    def test_both_packages_use_the_exact_reproducible_new_icons(self):
        with tempfile.TemporaryDirectory() as temporary:
            rendered = Path(temporary)
            render(rendered)
            for folder in (ROOT / "manifest", ROOT / "appPackage"):
                verify(folder)
                for name in ("color.png", "outline.png"):
                    with self.subTest(folder=folder.name, icon=name):
                        self.assertEqual(hashlib.sha256((folder / name).read_bytes()).digest(),
                                         hashlib.sha256((rendered / name).read_bytes()).digest())

    def test_web_titles_favicons_and_identity_use_the_new_name(self):
        for name in ("index.html", "control-plane.html"):
            html = (ROOT / "static" / name).read_text(encoding="utf-8")
            with self.subTest(surface=name):
                self.assertIn(f"<title>{NAME}", html)
                self.assertIn('href="/static/autopilot-icon.svg"', html)
                self.assertIn('src="/static/autopilot-icon.svg"', html)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(AgentIdentityContext.from_env().display_name, NAME)

    def test_operator_catalog_never_falls_back_to_retired_tenant(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = runpy.run_path(str(ROOT / "a365_value.py"))
        features = catalog["feature_catalog"]()
        self.assertIsNone(OLD.search(json.dumps(features)))
        self.assertEqual(catalog["TENANT_ID"], "<not-configured>")
        self.assertEqual(catalog["PUBLIC_ORIGIN"], "")
        self.assertEqual(catalog["BYO_MCP_SERVERS"], ())
        self.assertNotIn("has_any ()", json.dumps(features))

    def test_operator_catalog_uses_current_runtime_configuration(self):
        tenant = "17371818-07cb-47f2-9ca3-18f96f0125d7"
        environment = {
            "AZURE_TENANT_ID": tenant,
            "ENTRA_AGENT_BLUEPRINT_CLIENT_ID": BLUEPRINT,
            "ESS_PUBLIC_BASE_URL": "https://autopilot.example.invalid/",
            "AUTOPILOT_BYO_MCP_NAMES": "autopilot_tool,\"; arbitrary query",
        }
        with patch.dict(os.environ, environment, clear=True):
            catalog = runpy.run_path(str(ROOT / "a365_value.py"))
        self.assertEqual(catalog["TENANT_ID"], tenant)
        self.assertEqual(catalog["BLUEPRINT_APP"], BLUEPRINT)
        self.assertEqual(catalog["PUBLIC_ORIGIN"], "https://autopilot.example.invalid")
        self.assertEqual(catalog["BYO_MCP_SERVERS"], ("autopilot_tool",))
        self.assertIsNone(OLD.search(json.dumps(catalog["feature_catalog"]())))


if __name__ == "__main__":
    unittest.main()