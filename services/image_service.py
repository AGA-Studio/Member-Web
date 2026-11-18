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
# The business logo is also the Google Wallet pass logo, which needs at least
# 660 px (brand guidelines): it is stored bigger and shrunk by the client.
LOGO_MAX_DIMENSION = 1024
# Rejects "decompression bombs": tiny files that expand to huge bitmaps.
MAX_PIXELS = 25_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
WEBP_QUALITY = 85
CONTENT_TYPE = "image/webp"
PNG_CONTENT_TYPE = "image/png"
# Google masks the pass logo into a circle, so the artwork keeps a 15% margin.
PASS_LOGO_MARGIN = 0.15
# Square side of the pass logo; a 1024 px canvas is already above the 660 px
# minimum and keeps the file small.
PASS_LOGO_MAX_SIDE = 1024


class ImageRejected(ValueError):
    """The upload is not an image we accept."""


def to_webp(data: bytes, max_dimension: int = MAX_DIMENSION) -> bytes:
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
            image.thumbnail((max_dimension, max_dimension))
            output = BytesIO()
            # No `exif=` argument: the re-encoded file carries no metadata.
            image.save(output, format="WEBP", quality=WEBP_QUALITY)
    except (OSError, ValueError) as error:
        raise ImageRejected("The image could not be processed") from error
    return output.getvalue()


def to_pass_png(data: bytes) -> bytes:
    """A stored image as the square PNG the Google Wallet pass logo needs.

    Google's brand guidelines ask for a PNG of at least 660x660, a 1:1 aspect
    ratio and a 15% margin, because the logo is masked into a circle. The
    artwork is centered on a transparent square canvas instead of being
    stretched, so a wide logo is not distorted.
    """
    try:
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            # Always RGBA: the canvas is transparent and the artwork is its own
            # mask, so a logo with a background keeps it and one without gets
            # the pass background.
            image = image.convert("RGBA")
            artwork = max(image.width, image.height)
            side = min(round(artwork / (1 - 2 * PASS_LOGO_MARGIN)), PASS_LOGO_MAX_SIDE)
            inner = round(side * (1 - 2 * PASS_LOGO_MARGIN))
            image.thumbnail((inner, inner))
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)
            output = BytesIO()
            canvas.save(output, format="PNG")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as error:
        raise ImageRejected("The image could not be processed") from error
    return output.getvalue()
