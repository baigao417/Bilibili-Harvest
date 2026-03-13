import unittest
from unittest.mock import patch

import requests

from http_utils import HttpRequestError, request_json_with_retry, sanitize_cookie_header


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class HttpUtilsTests(unittest.TestCase):
    def test_sanitize_cookie_header(self):
        raw = "Cookie: SESSDATA=abc;  bili_jct=def\nDedeUserID=1"
        clean = sanitize_cookie_header(raw)
        self.assertEqual(clean, "SESSDATA=abc; bili_jct=def; DedeUserID=1")

    @patch("http_utils.time.sleep")
    @patch("http_utils.requests.get")
    def test_request_json_with_retry_on_connection_error(self, mock_get, _mock_sleep):
        mock_get.side_effect = [
            requests.ConnectionError("network down"),
            _FakeResponse(status_code=200, payload={"code": 0, "data": {"ok": True}}),
        ]

        payload = request_json_with_retry("https://example.com")
        self.assertEqual(payload["data"]["ok"], True)
        self.assertEqual(mock_get.call_count, 2)

    @patch("http_utils.time.sleep")
    @patch("http_utils.requests.get")
    def test_request_json_with_retry_on_retryable_status(self, mock_get, _mock_sleep):
        mock_get.side_effect = [
            _FakeResponse(status_code=503, payload={"code": -1}),
            _FakeResponse(status_code=200, payload={"code": 0}),
        ]

        payload = request_json_with_retry("https://example.com")
        self.assertEqual(payload["code"], 0)
        self.assertEqual(mock_get.call_count, 2)

    @patch("http_utils.requests.get")
    def test_request_json_non_retry_status_raises(self, mock_get):
        mock_get.return_value = _FakeResponse(status_code=404, payload={"code": -404})
        with self.assertRaises(HttpRequestError):
            request_json_with_retry("https://example.com")
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
