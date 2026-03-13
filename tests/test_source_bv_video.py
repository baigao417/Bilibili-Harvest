import unittest
from unittest.mock import patch

from plugins.sources.builtin_sources import BvVideoSourcePlugin
from plugins.types import SourceResolveOptions


class SourceBvVideoTests(unittest.TestCase):
    def setUp(self):
        self.plugin = BvVideoSourcePlugin()

    @patch("plugins.sources.builtin_sources._request_bili_json")
    def test_resolve_single_video(self, mock_request):
        mock_request.return_value = {
            "code": 0,
            "data": {
                "aid": 1,
                "cid": 2,
                "title": "Single Title",
                "owner": {"name": "UP"},
            },
        }

        items = self.plugin.resolve("https://www.bilibili.com/video/BV1TEST123", SourceResolveOptions())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "single")
        self.assertEqual(items[0].cid, 2)
        self.assertEqual(items[0].title, "Single Title")

    @patch("plugins.sources.builtin_sources._request_bili_json")
    def test_resolve_all_pages(self, mock_request):
        mock_request.side_effect = [
            {
                "code": 0,
                "data": {
                    "aid": 1,
                    "cid": 2,
                    "title": "Video Title",
                    "owner": {"name": "UP"},
                },
            },
            {
                "code": 0,
                "data": [
                    {"cid": 2, "page": 1, "part": "P1"},
                    {"cid": 3, "page": 2, "part": "P2"},
                ],
            },
        ]

        items = self.plugin.resolve(
            "BV1TEST123",
            SourceResolveOptions(import_mode="all_pages"),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "multi_p")
        self.assertEqual(items[1].page, 2)


if __name__ == "__main__":
    unittest.main()
