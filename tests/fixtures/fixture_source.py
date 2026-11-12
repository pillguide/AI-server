from io import BytesIO
from pathlib import Path
import base64
from PIL import Image

ROOT = Path(__file__).parent
XMP = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:a="http://ns.apple.com/pixeldatainfo/1.0/" xmlns:h="http://ns.apple.com/HDRGainMap/1.0/"><a:AuxiliaryImageType>urn:com:apple:photo:2020:aux:hdrgainmap</a:AuxiliaryImageType><h:HDRGainMapVersion>131072</h:HDRGainMapVersion></rdf:Description></rdf:RDF></x:xmpmeta>'''
with Image.new('RGB', (32, 24), (230, 20, 10)) as primary, Image.new('L', (16, 12), 128) as gain:
    gain.encoderinfo = {'xmp': XMP}
    primary.getexif()[274] = 6
    out = BytesIO()
    primary.save(out, format='MPO', save_all=True, append_images=[gain], exif=primary.getexif())
data = out.getvalue()
for target in [ROOT/'apple-hdr.jpg.b64']:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(base64.b64encode(data).decode()+'\n', encoding='ascii')
print('Synthetic HDR fixture:', len(data), 'bytes')
