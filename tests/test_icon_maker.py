import struct
import tempfile
import unittest
from pathlib import Path

from tools.PluginGenerator.icon_maker import (
    ICON_SYMBOLS,
    create_icon_png,
    parse_hex_color,
    render_icon_pixels,
)


class IconMakerTests(unittest.TestCase):
    def test_racing_template_catalog_is_comprehensive(self):
        self.assertGreaterEqual(len(ICON_SYMBOLS), 19)
        for symbol in ('helmet', 'trophy', 'pit-lane', 'track-map', 'brake-disc',
                       'suspension', 'engine', 'fuel', 'gear', 'lap-delta'):
            self.assertIn(symbol, ICON_SYMBOLS)

    def test_hex_colors_support_rgb_and_rgba(self):
        self.assertEqual((32, 36, 43, 255), parse_hex_color('#20242B'))
        self.assertEqual((32, 36, 43, 128), parse_hex_color('20242B80'))

    def test_invalid_color_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hexadecimal'):
            parse_hex_color('#ZZZZZZ')

    def test_every_symbol_renders_rgba_pixels(self):
        for symbol in ICON_SYMBOLS:
            with self.subTest(symbol=symbol):
                pixels = render_icon_pixels(32, '#000000', '#FFFFFF', symbol)
                self.assertEqual(32 * 32 * 4, len(pixels))
                self.assertIn(b'\xff\xff\xff\xff', pixels)

    def test_png_writer_creates_requested_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'icon.png'

            create_icon_png(path, size=64, symbol='pulse')
            data = path.read_bytes()

            self.assertEqual(b'\x89PNG\r\n\x1a\n', data[:8])
            width, height = struct.unpack('>II', data[16:24])
            self.assertEqual((64, 64), (width, height))

    def test_png_writer_defaults_to_atlas_icon_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'icon.png'

            create_icon_png(path, symbol='checkered-flag')
            data = path.read_bytes()

            self.assertEqual((16, 16), struct.unpack('>II', data[16:24]))

    def test_unknown_symbol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown icon symbol'):
            render_icon_pixels(32, '#000000', '#FFFFFF', 'car')


if __name__ == '__main__':
    unittest.main()
