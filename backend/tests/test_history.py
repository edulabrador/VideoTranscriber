import json
import tempfile
import unittest
from pathlib import Path

from backend.core.history import HistoryStore


class HistoryStoreTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
