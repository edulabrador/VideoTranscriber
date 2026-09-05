import unittest

from backend.core.validators import (
    is_cobalt_url,
    is_instagram_url,
    is_tiktok_url,
    is_x_url,
    is_youtube_url,
)


class SupportedUrlTests(unittest.TestCase):
    def test_supported_video_urls(self):
        self.assertTrue(is_instagram_url("https://www.instagram.com/reel/ABC_123/"))
        self.assertTrue(is_instagram_url("https://www.tiktok.com/@creator/video/1234567890"))
        self.assertTrue(is_instagram_url("https://vm.tiktok.com/ZM123abc/"))
        self.assertTrue(is_instagram_url("https://x.com/creator/status/1234567890"))
        self.assertTrue(
            is_instagram_url("https://twitter.com/creator/status/1234567890/video/1?s=20")
        )
        self.assertTrue(
            is_instagram_url("https://x.com/creator/status/1234567890/mediaViewer")
        )
        self.assertTrue(is_instagram_url("https://www.youtube.com/watch?v=BaW_jenozKc"))
        self.assertTrue(is_instagram_url("https://youtu.be/BaW_jenozKc?t=10"))
        self.assertTrue(is_instagram_url("https://www.youtube.com/shorts/BaW_jenozKc"))
        self.assertFalse(is_instagram_url("https://example.com/video/123"))

    def test_youtube_video_urls_without_accepting_channel_or_playlist_pages(self):
        self.assertTrue(is_youtube_url("https://music.youtube.com/watch?v=BaW_jenozKc"))
        self.assertTrue(is_youtube_url("https://www.youtube.com/live/BaW_jenozKc"))
        self.assertFalse(is_youtube_url("https://www.youtube.com/@creator"))
        self.assertFalse(is_youtube_url("https://www.youtube.com/playlist?list=PL123"))
        self.assertFalse(is_youtube_url("ftp://www.youtube.com/watch?v=BaW_jenozKc"))

    def test_tiktok_detection_is_separate_from_instagram(self):
        self.assertTrue(is_tiktok_url("https://www.tiktok.com/@creator/video/1234567890"))
        self.assertTrue(is_tiktok_url("https://vt.tiktok.com/ZM123abc/"))
        self.assertFalse(is_tiktok_url("https://www.instagram.com/reel/ABC_123/"))

    def test_cobalt_handles_tiktok_and_x(self):
        self.assertTrue(is_cobalt_url("https://www.tiktok.com/@creator/video/1234567890"))
        self.assertTrue(is_cobalt_url("https://x.com/creator/status/1234567890"))
        self.assertFalse(is_cobalt_url("https://www.instagram.com/reel/ABC_123/"))

    def test_x_detection(self):
        self.assertTrue(is_x_url("https://x.com/creator/status/1234567890"))
        self.assertTrue(is_x_url("https://twitter.com/creator/status/1234567890/video/1"))
        self.assertFalse(is_x_url("https://www.tiktok.com/@creator/video/1234567890"))


if __name__ == "__main__":
    unittest.main()
