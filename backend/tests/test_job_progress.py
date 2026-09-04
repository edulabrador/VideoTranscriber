import unittest

from backend.core.job_manager import JobManager


class JobProgressTests(unittest.TestCase):
    def test_explicit_progress_is_reported_and_clamped(self):
        manager = JobManager()
        job = manager.create_job()

        manager.update_status(job.id, "transcribing", "Procesando", 67)
        self.assertEqual(job.progress_percent, 67)

        manager.update_status(job.id, "transcribing", "Procesando", 120)
        self.assertEqual(job.progress_percent, 100)


if __name__ == "__main__":
    unittest.main()
