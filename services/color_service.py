"""Business brand color: which text color stays readable on top of it.

The frontend paints buttons with the business color (`--tenant-primary`) and
needs the text color that goes on them. A fixed white fails on light colors
(yellow, light green), so the API picks white or black by WCAG 2.x contrast.

Either white or black always reaches at least ~4.58:1 against any color, so the
better of the two always passes AA (4.5:1) for normal text: no color is
rejected for contrast.
"""

WHITE = "#ffffff"
BLACK = "#000000"
# WCAG 2.x, minimum contrast for normal text (level AA).
AA_CONTRAST = 4.5


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of "#rrggbb": 0 for black, 1 for white."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two "#rrggbb" colors, from 1 to 21."""
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_foreground(color: str | None) -> str | None:
    """White or black, whichever contrasts more with `color`. None without a color.

    Ties go to white, the Member+ default on the primary color.
    """
    if color is None:
        return None
    if contrast_ratio(color, WHITE) >= contrast_ratio(color, BLACK):
        return WHITE
    return BLACK
