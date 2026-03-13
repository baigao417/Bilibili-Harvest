import unittest

import local_api_server
from local_api_server import LocalApiServer


class LocalApiServerTests(unittest.TestCase):
    def _make_server(self) -> LocalApiServer:
        return LocalApiServer(
            command_handler=lambda _cmd, _payload: {"ok": True},
            runtime_state_provider=lambda: {"ok": True, "batch_running": False, "queue_size": 0},
        )

    def _make_test_client(self, app):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover - env dependent
            self.skipTest(f"fastapi testclient unavailable: {exc}")
        try:
            return TestClient(app)
        except Exception as exc:  # pragma: no cover - env dependent
            self.skipTest(f"fastapi testclient init unavailable: {exc}")

    def test_start_and_stop_or_graceful_failure(self):
        server = self._make_server()
        result = server.start(
            host="127.0.0.1",
            port=16780,
            port_scan_window=2,
            token="token",
            extension_ids=[],
        )

        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.assertFalse(result.ok)
            self.assertIn("fastapi", result.message.lower())
            return

        self.assertTrue(result.ok)
        self.assertGreater(result.port, 0)
        self.assertTrue(server.port > 0)
        server.stop()
        self.assertEqual(server.port, 0)

    def test_stop_without_start_is_safe(self):
        server = self._make_server()
        server.stop()
        self.assertEqual(server.port, 0)

    def test_origin_error_detail_message(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        server = self._make_server()
        server._token = "token"
        server._origins = ["http://127.0.0.1", "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        server._allow_extension_origin_regex = None
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.get(
            "/v1/health",
            headers={
                "origin": "chrome-extension://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "X-BilibiliHarvest-Token": "token",
            },
        )
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertIn("detail", payload)
        self.assertIn("extension_id", str(payload["detail"]))

    def test_empty_extension_ids_allows_valid_extension_origin(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        server = self._make_server()
        server._token = "token"
        server._origins = ["http://127.0.0.1", "http://localhost"]
        server._allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.get(
            "/v1/health",
            headers={
                "origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "X-BilibiliHarvest-Token": "token",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_empty_extension_ids_blocks_normal_web_origin(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        server = self._make_server()
        server._token = "token"
        server._origins = ["http://127.0.0.1", "http://localhost"]
        server._allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.get(
            "/v1/health",
            headers={
                "origin": "https://example.com",
                "X-BilibiliHarvest-Token": "token",
            },
        )
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertIn("detail", payload)
        self.assertIn("origin not allowed", str(payload["detail"]))

    def test_add_prefetched_route_dispatches_command(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        calls = []

        def _handler(command, payload):
            calls.append((command, payload))
            return {"ok": True, "accepted": 1, "duplicates": 0, "failed": 0}

        server = LocalApiServer(
            command_handler=_handler,
            runtime_state_provider=lambda: {"ok": True},
        )
        server._token = "token"
        server._origins = ["http://127.0.0.1", "http://localhost"]
        server._allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.post(
            "/v1/tasks/add_prefetched",
            headers={
                "origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "X-BilibiliHarvest-Token": "token",
            },
            json={
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {"segments": [{"start_sec": 0, "end_sec": 1, "text": "hello"}]},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(calls)
        self.assertEqual(calls[0][0], "add_prefetched")

    def test_pairing_info_route_dispatches_without_token(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        calls = []

        def _handler(command, payload):
            calls.append((command, payload))
            return {"ok": True, "pairable": True}

        server = LocalApiServer(command_handler=_handler, runtime_state_provider=lambda: {"ok": True})
        server._origins = ["http://127.0.0.1", "http://localhost"]
        server._allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.get("/v1/pairing/info", headers={"origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(calls)
        self.assertEqual(calls[0][0], "pairing_info")

    def test_config_route_requires_token(self):
        if local_api_server._FASTAPI_IMPORT_ERROR is not None:
            self.skipTest("fastapi unavailable in current environment")

        server = self._make_server()
        server._token = "token"
        server._origins = ["http://127.0.0.1", "http://localhost"]
        server._allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"
        app = server._build_app()
        client = self._make_test_client(app)

        response = client.get("/v1/config", headers={"origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
