import os
import tempfile
import unittest
from pathlib import Path

from filelock import FileLock, SoftFileLock, Timeout
from setuptools.wheel import Wheel


class DependencyCompatibilityTests(unittest.TestCase):
    def test_cache_file_lock_preserves_timeout_and_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.lock"
            holder = FileLock(path, timeout=0)
            contender = FileLock(path, timeout=0)
            with holder:
                self.assertTrue(holder.is_locked)
                with self.assertRaises(Timeout):
                    contender.acquire()
            with contender:
                self.assertTrue(contender.is_locked)
            self.assertFalse(contender.is_locked)

    def test_soft_lock_still_supports_context_management(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = SoftFileLock(Path(directory) / "soft.lock", timeout=0)
            with lock:
                self.assertTrue(lock.is_locked)
            self.assertFalse(lock.is_locked)

    @unittest.skipUnless(os.name == "nt", "Windows namespace path regression")
    def test_legacy_namespace_metadata_cannot_write_outside_destination(self):
        # Exercise metadata handling only. No external wheel, code execution, or
        # real installation is involved; both paths are inside this temporary root.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"
            outside = root / "outside"
            metadata = destination / "EGG-INFO"
            metadata.mkdir(parents=True)
            outside.mkdir()
            (metadata / "namespace_packages.txt").write_text(str(outside), encoding="utf-8")
            with self.assertRaises(ValueError):
                Wheel._fix_namespace_packages(str(metadata), str(destination))
            self.assertFalse((outside / "__init__.py").exists())


if __name__ == "__main__":
    unittest.main()
