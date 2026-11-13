"""services/image_service.py: only real images get through, re-encoded and clean."""

from io import BytesIO

import pytest
from PIL import Image

from services.image_service import MAX_DIMENSION, ImageRejected, to_webp
from tests.conftest import make_image


def open_webp(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    assert image.format == "WEBP"
    return image


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepted_formats_become_webp(fmt: str) -> None:
    open_webp(to_webp(make_image(fmt)))


def test_large_image_is_shrunk_keeping_proportions() -> None:
    image = open_webp(to_webp(make_image("PNG", size=(2000, 1000))))
    assert image.size == (MAX_DIMENSION, MAX_DIMENSION // 2)


def test_small_image_is_not_enlarged() -> None:
    assert open_webp(to_webp(make_image("PNG", size=(40, 30)))).size == (40, 30)


def test_transparency_is_kept() -> None:
    # A logo on a transparent background (an opaque image would drop the alpha).
    original = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    original.paste((0, 128, 128, 255), (16, 12, 48, 36))
    buffer = BytesIO()
    original.save(buffer, format="PNG")

    image = open_webp(to_webp(buffer.getvalue()))
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # The corner is still transparent.


def test_metadata_is_removed() -> None:
    # A phone photo: EXIF with the camera model and a GPS block (DLP).
    exif = Image.Exif()
    exif[0x0110] = "Phone X"  # Model
    exif[0x8825] = {2: (32.0, 31.0, 0.0)}  # GPSInfo: latitude
    original = make_image("JPEG", exif=exif.tobytes())
    assert Image.open(BytesIO(original)).getexif()  # The upload does carry EXIF.

    cleaned = open_webp(to_webp(original))
    assert not cleaned.getexif()
    assert "exif" not in cleaned.info


def test_exif_orientation_is_applied_before_dropping_it() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° when displayed.
    landscape = make_image("JPEG", size=(80, 40), exif=exif.tobytes())
    # The stored file is already upright, so it no longer needs the tag.
    assert open_webp(to_webp(landscape)).size == (40, 80)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"just some text, not an image", "not a valid image"),
        (b"%PDF-1.7\n" + b"0" * 200, "not a valid image"),
        (make_image("PNG")[:40], "not a valid image"),
    ],
    ids=["empty", "text", "pdf", "truncated"],
)
def test_non_images_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(ImageRejected, match=message):
        to_webp(data)


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_other_image_formats_are_rejected(fmt: str) -> None:
    with pytest.raises(ImageRejected, match="Only JPEG, PNG or WebP"):
        to_webp(make_image(fmt))


def test_too_many_pixels_is_rejected() -> None:
    # 6000 × 6000 = 36 M pixels in a few KB: a "decompression bomb".
    bomb = make_image("PNG", size=(6000, 6000), mode="1")
    assert len(bomb) < 100_000
    with pytest.raises(ImageRejected, match="too many pixels"):
        to_webp(bomb)


def test_extension_does_not_matter_only_content() -> None:
    # A PNG sent as "logo.jpg" is still a PNG: the name is never trusted.
    open_webp(to_webp(make_image("PNG")))


def test_header_ok_but_pixels_broken_is_rejected() -> None:
    # A JPEG cut in half: the header looks valid, decoding the pixels fails.
    whole = make_image("JPEG", size=(256, 256))
    with pytest.raises(ImageRejected, match="could not be processed"):
        to_webp(whole[: len(whole) // 2])
