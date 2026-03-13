import json
import os
import unittest


class BrowserExtensionManifestTests(unittest.TestCase):
    def test_manifest_has_required_mv3_fields(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest_path = os.path.join(root, "browser_extension", "manifest.json")
        self.assertTrue(os.path.isfile(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest.get("manifest_version"), 3)
        self.assertIn("background", manifest)
        self.assertIn("service_worker", manifest["background"])
        self.assertIn("action", manifest)

        permissions = set(manifest.get("permissions") or [])
        self.assertTrue({"storage", "activeTab", "tabs"}.issubset(permissions))

        host_permissions = manifest.get("host_permissions") or []
        self.assertIn("http://127.0.0.1/*", host_permissions)
        self.assertIn("http://localhost/*", host_permissions)


if __name__ == "__main__":
    unittest.main()
