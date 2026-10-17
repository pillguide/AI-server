from contextlib import closing
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImageError(ValueError):
    pass


class ImageTooLargeError(InvalidImageError):
    pass


class ImageDecoder:
    def __init__(self, max_pixels: int) -> None:
        self._max_pixels = max_pixels

    def decode(self, data: bytes) -> Image.Image:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with closing(Image.open(BytesIO(data))) as source:
                    if source.format not in ('JPEG', 'PNG'):
                        raise InvalidImageError('Only JPEG and PNG images are supported')
                    if getattr(source, 'n_frames', 1) != 1:
                        raise InvalidImageError('Animated images are not supported')
                    if source.width * source.height > self._max_pixels:
                        raise ImageTooLargeError('Image exceeds the pixel limit')
                    source.load()
                    with closing(ImageOps.exif_transpose(source)) as oriented:
                        return oriented.convert('RGB')
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ImageTooLargeError('Image exceeds the pixel limit') from None
        except InvalidImageError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            raise InvalidImageError('Invalid or corrupted image') from None
