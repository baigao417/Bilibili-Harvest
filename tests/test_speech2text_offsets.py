import os
import tempfile
import unittest
from unittest.mock import patch

import speech2text


class DummyWhisperModel:
    def transcribe(self, file_path, initial_prompt=None):
        name = os.path.basename(file_path)
        if name == "1.mp3":
            return {"segments": [{"start": 0.2, "end": 1.0, "text": "first"}]}
        return {"segments": [{"start": 0.5, "end": 1.4, "text": "second"}]}


class Speech2TextOffsetTests(unittest.TestCase):
    @patch("speech2text._ensure_ffmpeg_in_path", return_value="ffmpeg")
    @patch("speech2text._probe_audio_duration_seconds")
    def test_transcribe_to_segments_uses_absolute_offsets(self, mock_probe, _mock_ffmpeg):
        mock_probe.side_effect = [10.0, 8.0]

        with tempfile.TemporaryDirectory() as tmp:
            f1 = os.path.join(tmp, "1.mp3")
            f2 = os.path.join(tmp, "2.mp3")
            open(f1, "wb").close()
            open(f2, "wb").close()

            old_model = speech2text.whisper_model
            try:
                speech2text.whisper_model = DummyWhisperModel()
                segments = speech2text.transcribe_to_segments(tmp, model="small", prompt="test")
            finally:
                speech2text.whisper_model = old_model

            self.assertEqual(len(segments), 2)
            self.assertAlmostEqual(segments[0]["start_sec"], 0.2)
            self.assertAlmostEqual(segments[1]["start_sec"], 10.5)
            self.assertAlmostEqual(segments[1]["end_sec"], 11.4)


if __name__ == "__main__":
    unittest.main()
