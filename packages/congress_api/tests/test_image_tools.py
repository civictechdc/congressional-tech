"""Pillow verification is isolated and bounded, with actual pixel decoding."""
from io import BytesIO
import struct
import zlib
import subprocess

import pytest
from PIL import Image

from congress_api.retention import image_tools as reader
from congress_api.retention.capture_inspection import inspect_body


def encoded(kind):
    stream = BytesIO()
    Image.new('RGB', (20, 30), 'red').save(stream, format=kind)
    return stream.getvalue()


@pytest.mark.parametrize('kind', ['PNG', 'JPEG'])
def test_static_images_decode_with_fact_based_format(kind):
    body = encoded(kind)
    assert reader.image_info(body) == dict(format=kind.lower(), width=20, height=30)
    assert inspect_body(body, 'https://example.gov/deceptive.pdf', 'application/pdf') == ('saved', kind.lower())


@pytest.mark.parametrize('kind', ['PNG', 'JPEG'])
def test_truncation_rejected(kind):
    complete = encoded(kind)
    if kind == 'PNG':
        # Locate IDAT data, then remove required compressed pixels. A fixed
        # offset can leave the full image intact and cut only its trailer.
        offset = 8  # PNG signature
        while offset < len(complete):
            length = struct.unpack('>I', complete[offset:offset + 4])[0]
            chunk = complete[offset + 4:offset + 8]
            if chunk == b'IDAT':
                start = offset + 8
                cut = start + length // 2
                assert start < cut < start + length
                body = complete[:cut]
                compressed = complete[start:cut]
                decoder = zlib.decompressobj()
                decoder.decompress(compressed)
                assert not decoder.eof, 'Fixture must remove compressed image data'
                break
            offset += length + 12
        else:
            pytest.fail('PNG fixture has no IDAT chunk')
    else:
        # Cut within the JPEG entropy-coded scan, preserving its header while
        # removing encoded pixels and the end marker.
        marker = complete.index(b'\xff\xda')
        start = marker + 2 + struct.unpack('>H', complete[marker + 2:marker + 4])[0]
        end = complete.rindex(b'\xff\xd9')
        cut = start + (end - start) // 2
        assert start < cut < end
        body = complete[:cut]
    assert len(body) < len(complete)
    with pytest.raises(reader.ImageReadError):
        reader.image_info(body)
    assert inspect_body(body, 'https://example.gov/a.png', 'image/png')[0] == 'invalid_document'


def test_misleading_extension_is_not_image_proof():
    with pytest.raises(reader.ImageReadError):
        reader.image_info(b'not a picture')
    assert inspect_body(b'not a picture', 'https://example.gov/a.png', 'image/png')[0] != 'saved'


def test_oversized_dimensions_refused_without_decoding_pixels():
    data = bytearray(encoded('PNG'))
    data[16:24] = struct.pack('>II', 100000, 100000)
    data[29:33] = struct.pack('>I', zlib.crc32(data[12:29]))
    with pytest.raises(reader.ImageReadError):
        reader.image_info(bytes(data))


def test_reader_timeout_is_explicit(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 10
        raise subprocess.TimeoutExpired(args[0], 10)
    monkeypatch.setattr(reader.subprocess, 'run', timeout)
    with pytest.raises(reader.ImageReadError):
        reader.image_info(encoded('PNG'))


def test_byte_limit_is_checked_before_subprocess(monkeypatch):
    monkeypatch.setattr(reader, 'BODY_LIMIT', 10)
    monkeypatch.setattr(reader.subprocess, 'run', lambda *a, **k: pytest.fail('Should refuse before process'))
    with pytest.raises(reader.ImageReadError):
        reader.image_info(encoded('PNG'))
