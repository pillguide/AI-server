from pathlib import Path
from io import BytesIO
import base64, struct
from PIL import Image
from fixture_source import data, XMP, ROOT

cases = [('apple-hdr.jpg', data, '200')]
def add(name, value): cases.append((name, value, '415'))
add('wrong-byte-order', data.replace(b'MPF\0II', b'MPF\0XX').replace(b'MPF\0MM', b'MPF\0XX'))
add('wrong-auxiliary-type', data.replace(b'aux:hdrgainmap', b'aux:otherdata'))
add('wrong-xmp-namespace', data.replace(b'http://ns.apple.com/pixeldatainfo/1.0/', b'http://ns.other.com/pixeldatainfo/1.0/'))
add('unsupported-hdr-version', data.replace(b'>131072<', b'>999999<'))
add('truncated-auxiliary', data[:-8])
add('trailing-image', data + b'\xff\xd8\xff\xd9')
base = data.index(b'MPF\0') + 4
order = '<' if data[base:base+2] == b'II' else '>'
directory = base + struct.unpack_from(order+'I',data,base+4)[0]
n = struct.unpack_from(order+'H',data,directory)[0]
entries = None
for i in range(n):
 p = directory+2+i*12
 tag = struct.unpack_from(order+'H',data,p)[0]
 if tag==0xb002: entries=base+struct.unpack_from(order+'I',data,p+8)[0]
 if tag==0xb001:
  broken=bytearray(data);struct.pack_into(order+'I',broken,p+8,3);add('wrong-image-count',bytes(broken))
for name, position, value in [('overlapping-offset',entries+24,0), ('out-of-bounds-offset',entries+24,0xffffffff), ('wrong-primary-size',entries+4,4), ('out-of-bounds-size',entries+20,0xffffffff), ('dependent-image',entries+28,1)]:
 broken=bytearray(data);struct.pack_into(order+'I',broken,position,value);add(name,bytes(broken))
for name,flag in [('reserved-flag',0x10000000),('dependent-child-flag',0x40000000),('dependent-parent-flag',0x80000000)]:
 broken=bytearray(data);struct.pack_into(order+'I',broken,entries+16,flag);add(name,bytes(broken))
aux_start=base+struct.unpack_from(order+'I',data,entries+24)[0]
sos=data.index(b'\xff\xda',aux_start)+2
entropy_start=sos+int.from_bytes(data[sos:sos+2],'big')
broken=bytearray(data[:entropy_start]+b'\xff\xd9')
struct.pack_into(order+'I',broken,entries+20,len(broken)-aux_start)
add('empty-auxiliary-scan',bytes(broken))
representative=bytearray(data);struct.pack_into(order+'I',representative,entries,0x20030000)
cases.append(('representative-primary',bytes(representative),'200'))
def mpo(xmp, mode='L', size=(16,12), count=2):
 with Image.new('RGB',(32,24),(230,20,10)) as p, Image.new(mode,size) as a:
  p.getexif()[274]=6;a.encoderinfo={'xmp':xmp};out=BytesIO()
  p.save(out,format='MPO',save_all=True,append_images=[a]*(count-1),exif=p.getexif())
  return out.getvalue()
add('ordinary-mpo',mpo(b'<metadata/>'))
add('three-images',mpo(XMP,count=3))
add('color-auxiliary',mpo(XMP,mode='RGB'))
add('oversized-auxiliary',mpo(XMP,size=(33,24)))
add('xmp-with-dtd',mpo(b'<!DOCTYPE x [<!ENTITY v "131072">]>'+XMP.replace(b'>131072<',b'>&v;<')))
add('duplicate-xmp-property',mpo(XMP.replace(b'</rdf:Description>',b'<h:HDRGainMapVersion>131072</h:HDRGainMapVersion></rdf:Description>')))
add('malformed-xmp',mpo(XMP.replace(b'</rdf:RDF>',b'</bad:END>')))
attr=b'<rdf:Description rdf:about="" xmlns:a="http://ns.apple.com/pixeldatainfo/1.0/" xmlns:h="http://ns.apple.com/HDRGainMap/1.0/" a:AuxiliaryImageType="urn:com:apple:photo:2020:aux:hdrgainmap" h:HDRGainMapVersion="131072"/>'
prefix=XMP[:XMP.index(b'<rdf:Description')];suffix=b'</rdf:RDF></x:xmpmeta>'
cases.append(('attribute-xmp',mpo(prefix+attr+suffix),'200'))
for folder in [ROOT]:
 for name,content,status in cases: (folder/(name+'.b64')).write_text(base64.b64encode(content).decode()+'\n',encoding='ascii')
 (folder/'cases.tsv').write_text(''.join(name+'\t'+status+'\n' for name,_,status in cases),encoding='ascii')
print('Shared cases:',len(cases))
