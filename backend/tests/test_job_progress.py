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

    def test_evicts_oldest_finished_job_when_memory_limit_is_reached(self):
        manager = JobManager(max_jobs=2)
        first = manager.create_job("first")
        manager.create_job("active")
        manager.update_status(first.id, "failed", "Falló")

        manager.create_job("new")

        self.assertIsNone(manager.get_job("first"))
        self.assertIsNotNone(manager.get_job("active"))
        self.assertIsNotNone(manager.get_job("new"))


if __name__ == "__main__":
    unittest.main()
