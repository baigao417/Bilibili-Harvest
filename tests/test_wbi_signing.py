import unittest
from unittest.mock import patch

import bili_wbi


class WbiSigningTests(unittest.TestCase):
    def setUp(self):
        bili_wbi._cached_img_key = ""
        bili_wbi._cached_sub_key = ""
        bili_wbi._cached_at = 0.0

    @patch("bili_wbi.request_json_with_retry")
    @patch("bili_wbi.time.time", return_value=1700000000)
    def test_sign_wbi_params_generates_wts_and_w_rid(self, _mock_time, mock_request_json):
        mock_request_json.return_value = {
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/abc123.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/def456.png",
                }
            },
        }

        signed = bili_wbi.sign_wbi_params({"mid": "1", "pn": "1", "ps": "30"})
        self.assertIn("wts", signed)
        self.assertIn("w_rid", signed)
        self.assertEqual(len(signed["w_rid"]), 32)

    @patch("bili_wbi.request_json_with_retry")
    @patch("bili_wbi.time.time")
    def test_wbi_key_cache_reused_within_ttl(self, mock_time, mock_request_json):
        mock_time.return_value = 1700000000
        mock_request_json.return_value = {
            "code": 0,
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/abc123.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/def456.png",
                }
            },
        }

        k1 = bili_wbi.get_wbi_keys()
        k2 = bili_wbi.get_wbi_keys()
        self.assertEqual(k1, k2)
        self.assertEqual(mock_request_json.call_count, 1)

    @patch("bili_wbi.request_json_with_retry")
    @patch("bili_wbi.time.time", return_value=1700000000)
    def test_force_refresh_wbi_keys(self, _mock_time, mock_request_json):
        mock_request_json.side_effect = [
            {
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/abc123.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/def456.png",
                    }
                },
            },
            {
                "code": 0,
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/xyz111.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/uvw222.png",
                    }
                },
            },
        ]

        k1 = bili_wbi.get_wbi_keys()
        k2 = bili_wbi.get_wbi_keys(force_refresh=True)
        self.assertNotEqual(k1, k2)
        self.assertEqual(mock_request_json.call_count, 2)


if __name__ == "__main__":
    unittest.main()
