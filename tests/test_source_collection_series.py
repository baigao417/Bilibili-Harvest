import unittest
from unittest.mock import patch

from plugins.sources.builtin_sources import CollectionSeriesSourcePlugin
from plugins.types import SourceResolveOptions, SourceItem


class SourceCollectionSeriesTests(unittest.TestCase):
    def setUp(self):
        self.plugin = CollectionSeriesSourcePlugin()

    @patch("plugins.sources.builtin_sources._resolve_collection_archives")
    def test_collection_url_resolves_archives(self, mock_resolve_collection):
        mock_resolve_collection.return_value = (
            [
                {"bvid": "BV1A", "cid": 11, "title": "A", "author": "UPA"},
                {"bvid": "BV1B", "cid": 12, "title": "B", "author": "UPB"},
            ],
            100,
            "Collection Name",
        )

        items = self.plugin.resolve(
            "https://space.bilibili.com/100/channel/collectiondetail?sid=200",
            SourceResolveOptions(),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "collection")
        self.assertEqual(items[0].source_meta["container_id"], "season:200")

    @patch("plugins.sources.builtin_sources._resolve_series_archives")
    def test_series_lists_url_resolves_archives(self, mock_resolve_series):
        mock_resolve_series.return_value = (
            [{"bvid": "BV1C", "cid": 21, "title": "C", "author": "UPC"}],
            101,
            "Series Name",
        )

        items = self.plugin.resolve(
            "https://space.bilibili.com/101/lists/300",
            SourceResolveOptions(),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "series")
        self.assertEqual(items[0].source_meta["container_id"], "series:300")

    @patch("plugins.sources.builtin_sources._resolve_collection_archives")
    @patch("plugins.sources.builtin_sources._resolve_series_archives")
    def test_lists_type_season_uses_collection_api(self, mock_resolve_series, mock_resolve_collection):
        mock_resolve_collection.return_value = (
            [{"bvid": "BV1SEASON", "cid": 31, "title": "Season One", "author": "UPS"}],
            605727461,
            "Season Container",
        )

        items = self.plugin.resolve(
            "https://space.bilibili.com/605727461/lists/1283478?type=season",
            SourceResolveOptions(),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "collection")
        self.assertEqual(items[0].source_meta["container_id"], "season:1283478")
        self.assertTrue(mock_resolve_collection.called)
        self.assertFalse(mock_resolve_series.called)

    @patch("plugins.sources.builtin_sources._resolve_via_ytdlp_flat")
    @patch("plugins.sources.builtin_sources._resolve_collection_archives")
    def test_collection_falls_back_to_ytdlp(self, mock_resolve_collection, mock_fallback):
        mock_resolve_collection.side_effect = RuntimeError("api down")
        mock_fallback.return_value = [
            SourceItem(
                bvid="BV1FALL",
                source_type="collection",
                video_url="https://www.bilibili.com/video/BV1FALL",
            )
        ]

        items = self.plugin.resolve(
            "https://space.bilibili.com/100/channel/collectiondetail?sid=200",
            SourceResolveOptions(),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].bvid, "BV1FALL")
        self.assertTrue(mock_fallback.called)


if __name__ == "__main__":
    unittest.main()
