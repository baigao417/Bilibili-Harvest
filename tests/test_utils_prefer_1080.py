import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from utils import download_video_prefer_1080


class UtilsPrefer1080Tests(unittest.TestCase):
    @patch("utils.find_executable", return_value="yt-dlp")
    @patch("utils.run_command")
    def test_download_video_prefer_1080_uses_yt_dlp_format(self, mock_run_command, _mock_find):
        with tempfile.TemporaryDirectory() as tmp:
            media_path = os.path.join(tmp, "demo.mp4")

            def _fake_run(cmd, timeout=1800, cwd=None):
                with open(media_path, "w", encoding="utf-8") as f:
                    f.write("video")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run_command.side_effect = _fake_run
            out = download_video_prefer_1080(
                "BV1TEST",
                output_dir=tmp,
                cookie_header="SESSDATA=abc; bili_jct=def",
            )

            self.assertTrue(os.path.isfile(out))
            called_cmd = mock_run_command.call_args.args[0]
            joined = " ".join(called_cmd)
            self.assertIn("yt-dlp", called_cmd[0])
            self.assertIn("--merge-output-format", called_cmd)
            self.assertIn("mp4", called_cmd)
            self.assertIn("bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", joined)
            self.assertIn("--add-header", called_cmd)
            self.assertNotIn("you-get", joined)


if __name__ == "__main__":
    unittest.main()
