import json
import tempfile
import unittest
from pathlib import Path

from backend.core.history import HistoryStore, _source_key


class HistoryStoreTests(unittest.TestCase):
    def test_youtube_cache_key_uses_the_video_id(self) -> None:
        self.assertEqual(
            _source_key("https://www.youtube.com/watch?v=BaW_jenozKc&t=10"),
            _source_key("https://youtu.be/BaW_jenozKc"),
        )
        self.assertNotEqual(
            _source_key("https://www.youtube.com/watch?v=BaW_jenozKc"),
            _source_key("https://www.youtube.com/watch?v=OtherVideo"),
        )

    def test_only_two_latest_entries_include_transcript_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = [{"id": f"job_{index}"} for index in range(3)]
            history_path = root / "history.json"
            history_path.write_text(json.dumps(entries), encoding="utf-8")

            for index in range(3):
                job_dir = root / "output" / f"job_{index}"
                job_dir.mkdir(parents=True)
                (job_dir / "transcript.txt").write_text(f"texto {index}", encoding="utf-8")

            result = HistoryStore(history_path, 50, root / "output").list_entries()

            self.assertEqual([entry.get("text") for entry in result], ["texto 0", "texto 1", None])

    def test_finds_compatible_cached_url_ignoring_tracking_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            transcript_dir = output_dir / "job_cached"
            transcript_dir.mkdir(parents=True)
            history_path = root / "history.json"
            history_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "job_cached",
                            "source": "https://x.com/user/status/123?s=20",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (transcript_dir / "transcript.json").write_text(
                json.dumps(
                    {
                        "language": "es",
                        "language_probability": 0.99,
                        "duration": 10,
                        "text": "texto guardado",
                        "model_size": "large-v3-turbo",
                        "device": "cuda",
                        "compute_type": "int8_float16",
                        "batch_size": 4,
                        "profile": "balanced",
                        "audio_quality": "best",
                        "segments": [],
                    }
                ),
                encoding="utf-8",
            )

            store = HistoryStore(history_path, 50, output_dir)
            cached = store.find_cached(
                "https://x.com/user/status/123?utm_source=test", "balanced", "compact"
            )

            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached[0], "job_cached")
            self.assertEqual(cached[1].text, "texto guardado")
            self.assertIsNone(
                store.find_cached("https://x.com/user/status/123", "precise", "compact")
            )


if __name__ == "__main__":
    unittest.main()
