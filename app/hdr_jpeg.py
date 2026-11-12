"""Recognize the two-image Apple HDR JPEG profile, not arbitrary MPO files.

Offsets are validated against JPEG boundaries before any auxiliary pixels are decoded.
Only the base image is used for inference; no HDR rendering is performed.
"""
import struct
from xml.etree import ElementTree

XMP_PREFIX = b'http://ns.adobe.com/xap/1.0/\0'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
AUX = '{http://ns.apple.com/pixeldatainfo/1.0/}AuxiliaryImageType'
VERSION = '{http://ns.apple.com/HDRGainMap/1.0/}HDRGainMapVersion'


def _segments(data: bytes, start: int, end: int):
    if data[start:start + 2] != b'\xff\xd8':
        raise ValueError('Missing JPEG start')
    pos = start + 2
    entropy = False
    scan_data = False
    segment_count = 0
    while pos < end:
        if entropy:
            marker_at = data.find(b'\xff', pos, end)
            scan_data |= marker_at > pos
            pos = marker_at
            if pos < 0:
                break
        elif data[pos] != 255:
            raise ValueError('Invalid JPEG marker')
        while pos < end and data[pos] == 255:
            pos += 1
        if pos >= end:
            break
        marker = data[pos]
        pos += 1
        if entropy and (marker == 0 or 0xd0 <= marker <= 0xd7):
            scan_data |= marker == 0
            continue
        if entropy and not scan_data:
            raise ValueError('Empty JPEG scan')
        entropy = False
        if marker == 0xd9:
            if pos != end:
                raise ValueError('Unexpected bytes after JPEG')
            return
        if marker == 1:
            continue
        if marker == 0 or marker == 0xd8 or 0xd0 <= marker <= 0xd7 or pos + 2 > end:
            raise ValueError('Invalid JPEG marker')
        length = int.from_bytes(data[pos:pos + 2], 'big')
        if length < 2 or pos + length > end:
            raise ValueError('Invalid JPEG segment length')
        segment_count += 1
        if segment_count > 4096:
            raise ValueError('Too many JPEG segments')
        yield marker, pos + 2, pos + length
        pos += length
        entropy = marker == 0xda
        scan_data = False
    raise ValueError('Missing JPEG end')


def _apple_gain_map(xmp: bytes) -> bool:
    # JPEG APP1 bounds the input to <64 KiB. Reject declarations before parsing
    # UTF-8 XML so neither DTDs nor entity expansion are accepted.
    xml = xmp.decode('utf-8')
    if '\0' in xml or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        return False
    root = ElementTree.fromstring(xml)
    for description in root.iter(f'{{{RDF}}}Description'):
        values = dict(description.attrib)
        for child in description:
            if child.tag in (AUX, VERSION):
                if child.tag in values or len(child):
                    return False
                values[child.tag] = (child.text or '').strip()
        if values.get(AUX) == 'urn:com:apple:photo:2020:aux:hdrgainmap' and values.get(VERSION) == '131072':
            return True
    return False


def has_mp_index(data: bytes) -> bool:
    found = False
    for marker, start, end in _segments(data, 0, len(data)):
        found |= marker == 0xe2 and data[start:start + 4] == b'MPF\0'
        if marker == 0xda:
            break
    return found


def auxiliary_range(data: bytes) -> tuple[int, int]:
    """Return a validated auxiliary JPEG range or raise ValueError."""
    # Header walk stops at SOS: the primary length comes from the MP index.
    mpf = []
    for marker, start, end in _segments(data, 0, len(data)):
        if marker == 0xe2 and data[start:start + 4] == b'MPF\0':
            mpf.append((start + 4, end))
        if marker == 0xda:
            break
    if len(mpf) != 1:
        raise ValueError('Expected one MP index')
    base, limit = mpf[0]
    order = data[base:base + 2]
    if order not in (b'II', b'MM'):
        raise ValueError('Invalid MP byte order')
    endian = '<' if order == b'II' else '>'

    def read(kind, pos):
        size = struct.calcsize(kind)
        if pos < base or pos + size > limit:
            raise ValueError('MP index outside APP2')
        return struct.unpack_from(endian + kind, data, pos)[0]

    if read('H', base + 2) != 42:
        raise ValueError('Invalid MP TIFF header')
    directory = base + read('I', base + 4)
    if directory < base + 8:
        raise ValueError('Invalid MP directory')
    count = read('H', directory)
    tags = {}
    for index in range(count):
        pos = directory + 2 + index * 12
        tag, kind, number, value = read('H', pos), read('H', pos + 2), read('I', pos + 4), read('I', pos + 8)
        if tag in tags:
            raise ValueError('Duplicate MP tag')
        tags[tag] = (kind, number, value, pos)
    if read('I', directory + 2 + count * 12) != 0:
        raise ValueError('Unexpected MP directory')
    version, images, entries = tags.get(0xb000), tags.get(0xb001), tags.get(0xb002)
    if not version or version[:2] != (7, 4) or data[version[3] + 8:version[3] + 12] != b'0100':
        raise ValueError('Unsupported MP version')
    if not images or images[:3] != (4, 1, 2) or not entries or entries[:2] != (7, 32):
        raise ValueError('Expected two MP images')
    pos = base + entries[2]
    if pos < directory + 2 + count * 12 + 4:
        raise ValueError('MP entries overlap directory')
    spans = []
    for index in range(2):
        entry = pos + index * 16
        attr, size, offset = read('I', entry), read('I', entry + 4), read('I', entry + 8)
        allowed_attributes = (0x030000, 0x20030000) if index == 0 else (0,)
        if attr not in allowed_attributes or read('I', entry + 12) != 0:
            raise ValueError('Unsupported MP image attributes')
        if index == 0 and offset != 0:
            raise ValueError('Invalid primary offset')
        begin = 0 if index == 0 else base + offset
        if size < 4 or begin + size > len(data):
            raise ValueError('MP image outside file')
        spans.append((begin, begin + size))
    if spans[0][1] != spans[1][0] or spans[1][1] != len(data):
        raise ValueError('MP images must cover file without overlap')
    primary_segments = list(_segments(data, *spans[0]))
    if sum(m == 0xe2 and data[s:s + 4] == b'MPF\0' for m, s, e in primary_segments) != 1:
        raise ValueError('Duplicate MP index')
    xmps = []
    for marker, start, end in _segments(data, *spans[1]):
        if marker == 0xe2 and data[start:start + 4] == b'MPF\0':
            raise ValueError('Nested MP index')
        if marker == 0xe1 and data[start:start + len(XMP_PREFIX)] == XMP_PREFIX:
            xmps.append(data[start + len(XMP_PREFIX):end])
    try:
        valid = len(xmps) == 1 and _apple_gain_map(xmps[0])
    except (ElementTree.ParseError, UnicodeError):
        valid = False
    if not valid:
        raise ValueError('Not a supported Apple HDR auxiliary image')
    return spans[1]
