import os
import tempfile
import unittest

from plugins.manager import SourcePluginManager


class PluginManagerReloadTests(unittest.TestCase):
    def test_reload_applies_enabled_flags_and_required_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            enabled_file = os.path.join(tmp, "enabled.json")
            manager = SourcePluginManager(enabled_file=enabled_file, enable_scan=False)

            manager.save_enabled_config(
                {
                    "source.bv_video": False,  # required builtin, should stay enabled
                    "source.space_uploads": False,
                }
            )
            manager.reload(enable_scan=False)
            plugins = {item["id"]: item for item in manager.list_plugins()}

            self.assertTrue(plugins["source.bv_video"]["enabled"])
            self.assertFalse(plugins["source.space_uploads"]["enabled"])

    def test_reload_updates_scan_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            enabled_file = os.path.join(tmp, "enabled.json")
            manager = SourcePluginManager(enabled_file=enabled_file, enable_scan=False)
            self.assertFalse(manager.enable_scan)
            manager.reload(enable_scan=True)
            self.assertTrue(manager.enable_scan)


if __name__ == "__main__":
    unittest.main()
