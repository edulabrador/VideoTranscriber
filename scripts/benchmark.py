"""Measure cold/warm processing of a local file without changing user history."""

import argparse
import json
import tempfile
from pathlib import Path

from backend.config import settings
from backend.core import pipeline
from backend.core.history import HistoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()
    source = args.file.resolve()
    if not source.is_file() or args.runs < 1:
        parser.error("Provide an existing audio/video file and --runs >= 1")
    with tempfile.TemporaryDirectory(prefix="videotranscriber-benchmark-") as directory:
        root = Path(directory)
        settings.temp_dir = root / "temp"
        pipeline.history_store = HistoryStore(root / "history.json", args.runs, root / "output")
        for index in range(args.runs):
            result = pipeline.run_pipeline(
                f"job_benchmark_{index}", pipeline.FileSource(source, source.name),
                output_dir=root / "output" / f"job_benchmark_{index}",
            )
            print(json.dumps({
                "run": index + 1, "duration": result.duration, "device": result.device,
                "model": result.model_size, "word_count": result.word_count,
                "timings": result.timings,
            }), flush=True)


if __name__ == "__main__":
    main()
