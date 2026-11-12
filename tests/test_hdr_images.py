import base64
from pathlib import Path
import unittest
from app.imaging import InvalidImageError, ImageTooLargeError
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from test_application import ApplicationFixture

from app.imaging import ImageDecoder


def hdr_bytes():
    return base64.b64decode((Path(__file__).parent / 'fixtures/apple-hdr.jpg.b64').read_bytes())


class HdrImageTests(unittest.TestCase):
    def test_malformed_mpf_cannot_fall_back_to_ordinary_jpeg(self):
        data = hdr_bytes().replace(b'MPF\0II', b'MPF\0XX').replace(b'MPF\0MM', b'MPF\0XX')
        with self.assertRaises(InvalidImageError):
            ImageDecoder(20_000_000).decode(data)

    def test_hdr_jpeg_decodes_primary_rgb_with_primary_exif(self):
        with ImageDecoder(20_000_000).decode(hdr_bytes()) as image:
            self.assertEqual(image.size, (24, 32))
            self.assertEqual(image.mode, 'RGB')
            r, g, b = image.getpixel((12, 16))
            self.assertGreater(r, 200)
            self.assertLess(g, 40)
            self.assertLess(b, 40)

    def test_shared_hdr_structure_cases(self):
        root = Path(__file__).parent / 'fixtures'
        for line in (root / 'cases.tsv').read_text().splitlines():
            name, expected = line.split('\t')
            with self.subTest(name=name):
                data = base64.b64decode((root / (name + '.b64')).read_bytes())
                if expected == '415':
                    with self.assertRaises(InvalidImageError):
                        ImageDecoder(20_000_000).decode(data)
                else:
                    with ImageDecoder(20_000_000).decode(data) as image:
                        self.assertEqual(image.size, (24, 32))

    def test_hdr_pixel_cap_and_api_contract(self):
        with self.assertRaises(ImageTooLargeError):
            ImageDecoder(100).decode(hdr_bytes())
        fixture = ApplicationFixture()
        self.addCleanup(fixture.close)
        with TestClient(fixture.app) as client:
            response = client.post('/predict', headers=fixture.headers,
                                   files={'file': ('phone.jpg', hdr_bytes(), 'image/jpeg')})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['image'], {'width': 24, 'height': 32})
            self.assertEqual(fixture.engines[0].calls, 1)
            bad = hdr_bytes().replace(b'aux:hdrgainmap', b'aux:otherdata')
            self.assertEqual(client.post('/predict', headers=fixture.headers,
                                        files={'file': ('phone.jpg', bad, 'image/jpeg')}).status_code, 415)
            self.assertEqual(fixture.engines[0].calls, 1)

    def test_standard_phone_jpeg_and_png_orientations(self):
        for format in ('JPEG', 'PNG'):
            for orientation in range(1, 9):
                with self.subTest(format=format, orientation=orientation):
                    with Image.new('RGB', (32, 24), (230, 20, 10)) as source:
                        exif = source.getexif()
                        exif[274] = orientation
                        output = BytesIO()
                        source.save(output, format=format, exif=exif, progressive=True)
                    with ImageDecoder(20_000_000).decode(output.getvalue()) as decoded:
                        self.assertEqual(decoded.size, (24, 32) if orientation >= 5 else (32, 24))
