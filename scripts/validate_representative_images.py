"""Offline validation of the reviewed front image handoff. Never publishes data."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(manifest, supported, assets=None):
    """Check exact mapping; optionally decode and hash every private original."""
    require(manifest['schemaVersion'] == 1, 'unsupported manifest schema')
    require(manifest['sourceMappingSha256'] == supported['sourceMappingSha256'], 'model mapping hash differs')
    expected = supported['drugs']
    rows = manifest['images']
    require(len(expected) == len(rows) == 150, 'expected exactly 150 products')
    require(sorted(r['classId'] for r in rows) == list(range(150)), 'class IDs must be exactly 0..149')
    require(sorted(r['classId'] for r in expected) == list(range(150)), 'supported class IDs must be exactly 0..149')
    by_class = {r['classId']: r for r in expected}
    for field in ('itemSeq', 'productCode', 'relativePath', 'sha256', 'pixelSha256'):
        require(len({r[field] for r in rows}) == 150, f'duplicate {field}')
    root = Path(assets).resolve() if assets is not None else None
    for row in rows:
        expected_row = by_class[row['classId']]
        require(all(row[k] == expected_row[k] for k in ('itemSeq', 'productCode', 'modelName')), 'product mapping differs')
        require(row['side'] == 'front' and row['sideEvidence']['drugDir'] == '앞면', 'front evidence missing')
        require(row['relativePath'] == f"{row['classId']:03d}_{row['productCode']}/front.png", 'unexpected asset path')
        require(row['format'] == 'PNG' and row['width'] > 0 and row['height'] > 0 and row['bytes'] > 0, 'invalid image metadata')
        for key in ('sha256', 'pixelSha256'):
            require(len(row[key]) == 64 and all(c in '0123456789abcdef' for c in row[key]), 'invalid hash')
        if root is None:
            continue
        path = (root / row['relativePath']).resolve()
        require(path.is_relative_to(root), 'asset escapes root')
        data = path.read_bytes()
        require(len(data) == row['bytes'] and sha(data) == row['sha256'], 'file hash/size mismatch')
        with Image.open(path) as im:
            require(im.format == 'PNG', 'not PNG')
            im.verify()
        with Image.open(path) as im:
            im.load()
            rgb = im.convert('RGB')
            require(rgb.size == (row['width'], row['height']), 'dimensions differ')
            require(sha(str(rgb.size).encode() + rgb.tobytes()) == row['pixelSha256'], 'decoded pixels differ')
    return {'products': 150, 'filesDecoded': 150 if root else 0, 'bytes': sum(r['bytes'] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1] / 'provenance/representative-front-150.json')
    parser.add_argument('--supported', type=Path, required=True, help='Backend supported-drugs.json')
    parser.add_argument('--assets', type=Path, help='Private directory containing NNN_K-xxxxxx/front.png')
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    result = validate(json.loads(manifest_bytes), json.loads(args.supported.read_bytes()), args.assets)
    print(json.dumps({**result, 'manifestSha256': sha(manifest_bytes)}))


if __name__ == '__main__':
    main()
