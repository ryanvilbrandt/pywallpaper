from unittest import TestCase

from main import PyWallpaper


class TestPyWallpaper(TestCase):

    def test_parse_timestring(self):
        self.assertEqual(180.0, PyWallpaper.parse_timestring("3m"))
        self.assertEqual(10.0, PyWallpaper.parse_timestring("10s"))
        self.assertEqual(754.0, PyWallpaper.parse_timestring("12m34s"))
        self.assertEqual(32_763.0, PyWallpaper.parse_timestring("9h6m3s"))
        self.assertEqual(69.0, PyWallpaper.parse_timestring(69))
        self.assertEqual(4.20, PyWallpaper.parse_timestring(4.20))
