import unittest

from window import SOURCE_TYPE_LABELS


class SourceTypeLabelTests(unittest.TestCase):
    def test_source_type_label_mapping(self):
        self.assertEqual(SOURCE_TYPE_LABELS["single"], "单视频")
        self.assertEqual(SOURCE_TYPE_LABELS["multi_p"], "分P")
        self.assertEqual(SOURCE_TYPE_LABELS["favorite"], "收藏夹")
        self.assertEqual(SOURCE_TYPE_LABELS["collection"], "合集")
        self.assertEqual(SOURCE_TYPE_LABELS["series"], "列表")
        self.assertEqual(SOURCE_TYPE_LABELS["space_uploads"], "主页投稿")


if __name__ == "__main__":
    unittest.main()
