"""Turn an uploaded file into a safe, small WebP image.

Every upload is decoded and re-encoded, never stored as received:
- only real JPEG, PNG or WebP images get through (a renamed file or a polyglot
  fails to decode);
- the orientation from EXIF is applied and then all metadata is dropped, so a
  phone photo does not leak its GPS position or device data (DLP);
- the image is shrunk to fit MAX_DIMENSION and stored as WebP.
"""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 512
# Rejects "decompression bombs": tiny files that expand to huge bitmaps.
MAX_PIXELS = 25_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
WEBP_QUALITY = 85
CONTENT_TYPE = "image/webp"


class ImageRejected(ValueError):
    """The upload is not an image we accept."""


def to_webp(data: bytes) -> bytes:
    if not data:
        raise ImageRejected("The file is empty")
    try:
        with Image.open(BytesIO(data)) as probe:
            image_format = probe.format
            width, height = probe.size
            probe.verify()  # Structural check without decoding the pixels.
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as error:
        raise ImageRejected("The file is not a valid image") from error

    if image_format not in ALLOWED_FORMATS:
        raise ImageRejected("Only JPEG, PNG or WebP images are accepted")
    if width * height > MAX_PIXELS:
        raise ImageRejected("The image has too many pixels")

    try:
        # verify() leaves the image unusable: open it again to decode it.
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
            output = BytesIO()
            # No `exif=` argument: the re-encoded file carries no metadata.
            image.save(output, format="WEBP", quality=WEBP_QUALITY)
    except (OSError, ValueError) as error:
        raise ImageRejected("The image could not be processed") from error
    return output.getvalue()
