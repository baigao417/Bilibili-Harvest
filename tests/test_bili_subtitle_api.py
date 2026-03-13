import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bili_subtitle_api import (
    ApiTrack,
    discover_bili_tracks,
    ensure_task_identifiers,
    fetch_bili_track_segments,
    validate_cookie_login,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


class BiliSubtitleApiTests(unittest.TestCase):
    @patch("http_utils.requests.get")
    def test_validate_cookie_login_success(self, mock_get):
        mock_get.return_value = FakeResponse({"code": 0, "data": {"isLogin": True, "uname": "tester"}})
        ok, detail = validate_cookie_login("SESSDATA=ok")
        self.assertTrue(ok)
        self.assertIn("isLogin=true", detail)
        self.assertIn("tester", detail)

    @patch("http_utils.requests.get")
    def test_validate_cookie_login_fail(self, mock_get):
        mock_get.return_value = FakeResponse({"code": 0, "data": {"isLogin": False}})
        ok, detail = validate_cookie_login("SESSDATA=bad")
        self.assertFalse(ok)
        self.assertIn("isLogin=false", detail)

    def test_validate_cookie_login_missing_sessdata(self):
        ok, detail = validate_cookie_login("bili_jct=abc; DedeUserID=1")
        self.assertFalse(ok)
        self.assertIn("missing SESSDATA", detail)

    @patch("http_utils.requests.get")
    def test_discover_tracks_wbi_success_and_lang_normalized(self, mock_get):
        mock_get.return_value = FakeResponse(
            {
                "code": 0,
                "data": {
                    "subtitle": {
                        "subtitles": [
                            {"lan": "zh-cn", "subtitle_url": "//aisubtitle.hdslb.com/a.json"},
                            {"lan": "ai-zh", "subtitle_url": "//aisubtitle.hdslb.com/b.json"},
                            {"lan": "danmaku", "subtitle_url": "https://comment.bilibili.com/1.xml"},
                        ]
                    }
                },
            }
        )

        task = SimpleNamespace(
            bv="BV1TEST",
            aid=1,
            cid=2,
            video_link="https://www.bilibili.com/video/BV1TEST",
        )
        tracks, meta = discover_bili_tracks(task, cookie_header="SESSDATA=ok")
        langs = sorted([track.lang for track in tracks])
        self.assertEqual(langs, ["ai-zh", "zh-CN"])
        self.assertEqual(meta.endpoint_used, "wbi_v2")

    @patch("http_utils.requests.get")
    def test_discover_tracks_fallback_to_v2(self, mock_get):
        mock_get.side_effect = [
            FakeResponse({"code": -400, "message": "bad request"}),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "subtitle": {
                            "subtitles": [
                                {"lan": "zh-Hans", "subtitle_url": "//aisubtitle.hdslb.com/a.json"},
                            ]
                        }
                    },
                }
            ),
        ]

        task = SimpleNamespace(
            bv="BV1TEST",
            aid=1,
            cid=2,
            video_link="https://www.bilibili.com/video/BV1TEST",
        )
        tracks, meta = discover_bili_tracks(task, cookie_header="SESSDATA=ok")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].lang, "zh-Hans")
        self.assertEqual(meta.endpoint_used, "v2")
        self.assertEqual(mock_get.call_count, 2)

    @patch("http_utils.requests.get")
    def test_fetch_track_segments_resolves_ai_search_stat(self, mock_get):
        mock_get.side_effect = [
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "subtitle_url": "//aisubtitle.hdslb.com/track.json",
                    },
                }
            ),
            FakeResponse(
                {
                    "body": [
                        {"from": 0.1, "to": 1.5, "content": "hello"},
                        {"from": 1.6, "to": 2.0, "content": "world"},
                    ]
                }
            ),
        ]

        task = SimpleNamespace(
            bv="BV1TEST",
            aid=1,
            cid=2,
            video_link="https://www.bilibili.com/video/BV1TEST",
        )
        track = ApiTrack(lang="ai-zh", track_type="ai", subtitle_url="", raw_lang="ai-zh", endpoint="v2")
        segments = fetch_bili_track_segments(task, track, cookie_header="SESSDATA=ok")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "hello")
        self.assertAlmostEqual(segments[1]["end_sec"], 2.0)
        self.assertIn("/x/player/v2/ai/subtitle/search/stat", mock_get.call_args_list[0].args[0])

    @patch("http_utils.requests.get")
    def test_ensure_task_identifiers_fills_missing_ids(self, mock_get):
        mock_get.return_value = FakeResponse(
            {
                "code": 0,
                "data": {
                    "aid": 123,
                    "cid": 456,
                    "title": "Video Title",
                    "owner": {"name": "UPName"},
                },
            }
        )

        task = SimpleNamespace(
            bv="BV1TEST",
            aid=None,
            cid=None,
            title="UnknownTitle",
            owner="UnknownUP",
            video_link="https://www.bilibili.com/video/BV1TEST",
        )
        ensure_task_identifiers(task, cookie_header="SESSDATA=ok")
        self.assertEqual(task.aid, 123)
        self.assertEqual(task.cid, 456)
        self.assertEqual(task.title, "Video Title")
        self.assertEqual(task.owner, "UPName")


if __name__ == "__main__":
    unittest.main()
