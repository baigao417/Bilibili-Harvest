import unittest
from unittest.mock import patch

from plugins.sources.builtin_sources import SpaceUploadsSourcePlugin
from plugins.types import SourceResolveOptions, SourceItem


class SourceSpaceUploadsTests(unittest.TestCase):
    def setUp(self):
        self.plugin = SpaceUploadsSourcePlugin()

    @patch("plugins.sources.builtin_sources._resolve_space_upload_archives")
    def test_space_resolve_uses_wbi_archives(self, mock_resolve_archives):
        mock_resolve_archives.return_value = [
            {"bvid": "BV1A", "aid": 1, "cid": 11, "title": "A", "author": "UPA"},
            {"bvid": "BV1B", "aid": 2, "cid": 12, "title": "B", "author": "UPA"},
        ]

        items = self.plugin.resolve(
            "https://space.bilibili.com/12345",
            SourceResolveOptions(limit=1, order="pubdate_desc"),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "space_uploads")
        self.assertEqual(items[0].source_meta["mid"], 12345)

    @patch("plugins.sources.builtin_sources._resolve_via_ytdlp_flat")
    @patch("plugins.sources.builtin_sources._resolve_space_upload_archives")
    def test_space_fallback_to_ytdlp(self, mock_resolve_archives, mock_resolve_flat):
        mock_resolve_archives.side_effect = RuntimeError("wbi failed")
        mock_resolve_flat.return_value = [
            SourceItem(
                bvid="BV1FALL",
                source_type="space_uploads",
                video_url="https://www.bilibili.com/video/BV1FALL",
            )
        ]

        items = self.plugin.resolve(
            "12345",
            SourceResolveOptions(limit=200),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].bvid, "BV1FALL")
        self.assertTrue(mock_resolve_flat.called)


if __name__ == "__main__":
    unittest.main()
