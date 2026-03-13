import queue
import threading
import unittest

from window import MainWindow


class _InlineSignal:
    def __init__(self, callback):
        self._callback = callback

    def emit(self):
        self._callback()


class _FakeApiWindow:
    _api_command_handler = MainWindow._api_command_handler
    _process_api_commands = MainWindow._process_api_commands

    def __init__(self):
        self._api_command_queue = queue.Queue()
        self._tasks = []
        self.api_command_signal = _InlineSignal(self._process_api_commands)

    def _handle_api_add(self, payload):
        return {
            "ok": True,
            "accepted": 1 if payload.get("input") else 0,
            "duplicates": 0,
            "failed": 0 if payload.get("input") else 1,
            "queued_total": 0,
            "warnings": [],
        }

    def _handle_api_bulk_add(self, payload):
        items = payload.get("items") or []
        return {
            "ok": True,
            "accepted": len(items),
            "duplicates": 0,
            "failed": 0,
            "queued_total": 0,
            "item_results": [],
            "warnings": [],
        }

    def _handle_api_add_prefetched(self, payload):
        ok = bool(payload.get("input"))
        return {
            "ok": ok,
            "accepted": 1 if ok else 0,
            "duplicates": 0,
            "failed": 0 if ok else 1,
            "queued_total": 0,
            "warnings": [],
            "prefetch_bound": bool(ok),
            "prefetch_reason": "bound" if ok else "input_missing",
        }

    def _log(self, *_args, **_kwargs):
        return None


class ApiQueueThreadSafetyTests(unittest.TestCase):
    def test_concurrent_api_command_handler(self):
        fake = _FakeApiWindow()
        results = []
        errors = []
        lock = threading.Lock()

        def worker(i: int):
            try:
                resp = fake._api_command_handler("add", {"input": f"url-{i}"})
                with lock:
                    results.append(resp)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertFalse(errors)
        self.assertEqual(len(results), 20)
        self.assertTrue(all(bool(item.get("ok")) for item in results))

    def test_concurrent_api_add_prefetched_handler(self):
        fake = _FakeApiWindow()
        results = []
        errors = []
        lock = threading.Lock()

        def worker(i: int):
            try:
                resp = fake._api_command_handler(
                    "add_prefetched",
                    {
                        "input": f"https://www.bilibili.com/video/BV{i:010d}",
                        "prefetched_subtitle": {
                            "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "ok"}],
                        },
                    },
                )
                with lock:
                    results.append(resp)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertFalse(errors)
        self.assertEqual(len(results), 20)
        self.assertTrue(all(bool(item.get("ok")) for item in results))
        self.assertTrue(all(bool(item.get("prefetch_bound")) for item in results))


if __name__ == "__main__":
    unittest.main()
