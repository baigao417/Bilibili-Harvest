import os
import tempfile
import unittest

from runtime_config import DEFAULT_ARCHIVE_ROOT, DEFAULT_API_TOKEN, RuntimeConfig, load_runtime_config, reset_api_token, save_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_load_creates_default_file_with_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            cfg = load_runtime_config(path=path)
            self.assertTrue(os.path.isfile(path))
            self.assertIsInstance(cfg, RuntimeConfig)
            self.assertTrue(cfg.http_enabled)
            self.assertTrue(cfg.api_token)
            self.assertNotEqual(cfg.api_token, DEFAULT_API_TOKEN)
            self.assertTrue(cfg.archive_root.endswith("BilibiliHarvest Library"))
            self.assertEqual(cfg.archive_label, "本地知识库")

    def test_save_and_reload_normalizes_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            cfg = RuntimeConfig(
                http_enabled=True,
                http_host="",
                http_port=16780,
                http_port_scan_window=20,
                api_token="abc",
                extension_ids=["", " test ", " "],
                io_workers=99,
            )
            save_runtime_config(cfg, path=path)
            loaded = load_runtime_config(path=path)
            self.assertEqual(loaded.http_host, "127.0.0.1")
            self.assertEqual(loaded.io_workers, 4)
            self.assertEqual(loaded.extension_ids, ["test"])
            self.assertTrue(os.path.isabs(loaded.archive_root))
            self.assertEqual(loaded.archive_label, "本地知识库")

    def test_reset_api_token_changes_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            cfg = load_runtime_config(path=path)
            old = cfg.api_token
            new_token = reset_api_token(cfg, path=path)
            self.assertNotEqual(old, new_token)
            reloaded = load_runtime_config(path=path)
            self.assertEqual(reloaded.api_token, new_token)

    def test_custom_token_is_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            custom = "my_custom_token"
            cfg = RuntimeConfig(api_token=custom)
            save_runtime_config(cfg, path=path)
            loaded = load_runtime_config(path=path)
            self.assertEqual(loaded.api_token, custom)

    def test_shape_root_migrates_to_archive_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"shape_root":"C:/archive-old","api_token":"keep_me","archive_label":"Shape"}')
            loaded = load_runtime_config(path=path)
            self.assertTrue(loaded.archive_root.lower().endswith("archive-old"))
            self.assertEqual(loaded.api_token, "keep_me")
            self.assertEqual(loaded.archive_label, "Shape")


if __name__ == "__main__":
    unittest.main()
