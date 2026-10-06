"""Validate static PNG/JPEG bytes with Pillow in a bounded disposable process."""

from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

BODY_LIMIT = 16 * 1024**2
PIXEL_LIMIT = 16_000_000
TIMEOUT = 10


class ImageReadError(ValueError):
    """The image is unsupported, incomplete, or exceeds reader bounds."""


def image_kind(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    return None


def reader_version():
    return version('Pillow')


def image_info(data):
    """Verify structure and decode pixels; headers alone cannot establish validity."""
    if not image_kind(data) or len(data) > BODY_LIMIT:
        raise ImageReadError('Unsupported image or image byte limit exceeded')
    with TemporaryDirectory(prefix='image-read-') as directory:
        source = Path(directory) / 'source'
        source.write_bytes(data)
        try:
            result = subprocess.run(
                [sys.executable, '-m', __name__, str(source)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=TIMEOUT, check=True,
            )
            return json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise ImageReadError('Image reader rejected bytes or exceeded bounds') from exc


def _read(path):
    # The subprocess owns these globals. Concurrent parent readers never change
    # Pillow settings in one another's threads or retain decoded image pixels.
    import resource
    import warnings
    from PIL import Image, PngImagePlugin

    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    if sys.platform == 'linux':  # macOS does not implement a usable address-space limit.
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    Image.MAX_IMAGE_PIXELS = PIXEL_LIMIT
    PngImagePlugin.MAX_TEXT_CHUNK = 1024**2
    PngImagePlugin.MAX_TEXT_MEMORY = 4 * 1024**2
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    with Image.open(path, formats=('PNG', 'JPEG')) as image:
        if image.width * image.height > PIXEL_LIMIT or getattr(image, 'n_frames', 1) != 1:
            raise ImageReadError('Only bounded static images are supported')
        info = dict(format=image.format.lower(), width=image.width, height=image.height)
        image.verify()
    with Image.open(path, formats=('PNG', 'JPEG')) as image:
        image.load()
    return info


if __name__ == '__main__':
    print(json.dumps(_read(sys.argv[1])))
