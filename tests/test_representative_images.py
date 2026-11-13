import copy
import json
import unittest
from pathlib import Path

from scripts.validate_representative_images import validate


class RepresentativeImagesTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((Path(__file__).resolve().parents[1] / 'provenance/representative-front-150.json').read_text(encoding='utf-8'))
        self.supported = {'sourceMappingSha256': self.manifest['sourceMappingSha256'],
                          'drugs': [{k: r[k] for k in ('classId', 'productCode', 'itemSeq', 'modelName')}
                                    for r in self.manifest['images']]}

    def test_checked_in_manifest_has_exact_unique_150(self):
        self.assertEqual(validate(self.manifest, self.supported)['products'], 150)

    def test_wrong_product_is_rejected(self):
        self.manifest['images'][0]['itemSeq'] = '000000000'
        with self.assertRaisesRegex(ValueError, 'mapping differs'):
            validate(self.manifest, self.supported)

    def test_missing_or_duplicate_product_is_rejected(self):
        for replacement in [self.manifest['images'][:-1], self.manifest['images'][:-1] + [copy.deepcopy(self.manifest['images'][0])]]:
            with self.subTest(size=len(replacement)), self.assertRaises(ValueError):
                validate({**self.manifest, 'images': replacement}, self.supported)

    def test_back_image_is_rejected(self):
        self.manifest['images'][0]['sideEvidence']['drugDir'] = '뒷면'
        with self.assertRaisesRegex(ValueError, 'front evidence'):
            validate(self.manifest, self.supported)

    def test_path_substitution_is_rejected(self):
        self.manifest['images'][0]['relativePath'] = '../front.png'
        with self.assertRaisesRegex(ValueError, 'asset path'):
            validate(self.manifest, self.supported)

    def test_reused_file_is_rejected(self):
        self.manifest['images'][0]['sha256'] = self.manifest['images'][1]['sha256']
        with self.assertRaisesRegex(ValueError, 'duplicate sha256'):
            validate(self.manifest, self.supported)
