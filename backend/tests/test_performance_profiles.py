import unittest

from backend.core.model_manager import recommended_batch_size
from backend.core.transcriber import resolve_profile_settings


class PerformanceProfileTests(unittest.TestCase):
    def test_profiles_select_expected_models_and_beam_sizes(self) -> None:
        self.assertEqual(resolve_profile_settings("fast", "large-v3-turbo", 2), ("small", 1))
        self.assertEqual(
            resolve_profile_settings("balanced", "large-v3-turbo", 2),
            ("large-v3-turbo", 2),
        )
        self.assertEqual(resolve_profile_settings("precise", "small", 1), ("large-v3", 5))

    def test_batch_size_is_conservative_for_six_gigabyte_gpu(self) -> None:
        self.assertEqual(recommended_batch_size(6144, "balanced"), 4)
        self.assertEqual(recommended_batch_size(6144, "precise"), 4)

    def test_batch_size_scales_with_available_vram(self) -> None:
        self.assertEqual(recommended_batch_size(3072, "balanced"), 2)
        self.assertEqual(recommended_batch_size(8192, "balanced"), 8)
        self.assertEqual(recommended_batch_size(16384, "balanced"), 16)
        self.assertEqual(recommended_batch_size(None, "balanced"), 4)


if __name__ == "__main__":
    unittest.main()
