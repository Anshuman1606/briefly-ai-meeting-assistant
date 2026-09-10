"""Regression coverage for long transcripts and incremental media decoding."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from briefly import intelligence as ai
from briefly.service import Service


class LargeInputTests(unittest.TestCase):
    def test_long_transcript_end_to_end_and_late_evidence(self):
        text = "\n".join(f"[00:01] Discussion topic number {i} has an ordinary update." for i in range(5000))
        text += "\n[11:45:00] Priya will deliver the zirconium report by Friday."
        self.assertGreater(len(text), 100000)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"APP_ENV": "local", "ALLOW_SIGNUP": "true", "AUTH_MODE": "password", "MISTRAL_API_KEY": ""}):
            service = Service("sqlite:///" + str(Path(root) / "test.db"))
            owner = service.register("owner", "owner@example.test", "Long-test-password-123!", "Large input test")
            mid = service.create_meeting(owner, "Long recording", "transcript", transcript=text)
            self.assertTrue(service.process_next())
            meeting = service.get_meeting(owner, mid)
            self.assertEqual(meeting["status"], "ready", meeting["error"])
            self.assertEqual(len(meeting["chunks"]), 5001)
            answer = service.ask(owner, mid, "Who will deliver the zirconium report?")
            self.assertIn("zirconium", str(answer))
            self.assertEqual(meeting["chunks"][-1]["start"], 42300)
            service.engine.dispose()

    def test_provider_batches_visit_every_segment_and_keep_late_actions(self):
        text = "\n".join(f"Person{i} will finish deliverable {i} by Friday." for i in range(2400))
        visited = []
        def provider(task, data, schema):
            rows = data["transcript_segments"]
            self.assertLessEqual(len(rows), ai.ANALYSIS_BATCH_SEGMENTS)
            self.assertLessEqual(len(json.dumps(rows, ensure_ascii=False).encode()), ai.ANALYSIS_BATCH_BYTES)
            visited.extend(row["index"] for row in rows)
            return {"summary": [rows[0]["text"]], "decisions": [], "questions": [], "actions": [{"text": row["text"], "evidence": row["text"], "owner": "", "deadline": "Friday"} for row in rows]}
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test"}), patch.object(ai, "_mistral_json", side_effect=provider):
            result = ai.analyze_transcript(text)
        self.assertEqual(visited, list(range(2400)))
        self.assertEqual(len(result["actions"]), 2400)
        self.assertIn("2399", result["actions"][-1]["text"])
        self.assertLessEqual(len(result["summary"]), 5)

    def test_whisper_batches_preserve_timestamp_offsets(self):
        model = SimpleNamespace(transcribe=lambda *a, **kw: (iter([SimpleNamespace(start=2, text="Speech here.")]), None))
        with patch.object(ai, "_whisper_model", return_value=model), patch.object(ai, "_audio_batches", return_value=iter([(0, object()), (300, object()), (4320, object())])):
            result = ai._transcribe_whisper(Path("unused.wav"), "auto")
        self.assertIn("[00:05:02]", result)
        self.assertIn("[01:12:02]", result)

    def test_decoder_has_bounded_blocks_without_lost_samples(self):
        try:
            import av  # noqa: F401
        except ImportError:
            self.skipTest("optional Whisper decoder is not installed")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audio.wav"
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16000)
                out.writeframes(b"\x01\x00" * (16000 * 7))
            blocks = list(ai._audio_batches(path, seconds=3))
        self.assertEqual([offset for offset, _ in blocks], [0, 3, 6])
        self.assertEqual([len(block) for _, block in blocks], [48000, 48000, 16000])

    def test_unicode_limit_counts_bytes(self):
        with patch.object(ai, "MAX_TRANSCRIPT_BYTES", 10):
            with self.assertRaises(ai.IntelligenceError):
                ai.split_transcript("हिंदी")
