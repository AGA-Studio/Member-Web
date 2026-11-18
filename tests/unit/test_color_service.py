"""services/color_service.py: the text color that stays readable on the brand color."""

import pytest

from services.color_service import (
    AA_CONTRAST,
    BLACK,
    WHITE,
    contrast_ratio,
    readable_foreground,
    relative_luminance,
)


def test_luminance_of_the_extremes() -> None:
    assert relative_luminance("#000000") == 0
    assert relative_luminance("#ffffff") == pytest.approx(1)


def test_black_on_white_is_21_to_1_in_any_order() -> None:
    assert contrast_ratio(BLACK, WHITE) == pytest.approx(21)
    assert contrast_ratio(WHITE, BLACK) == pytest.approx(21)


def test_a_color_against_itself_is_1_to_1() -> None:
    assert contrast_ratio("#0062f2", "#0062f2") == pytest.approx(1)


@pytest.mark.parametrize(
    ("color", "foreground"),
    [
        ("#0062f2", WHITE),  # Member+ blue keeps its white text.
        ("#1f2937", WHITE),  # dark gray
        ("#b91c1c", WHITE),  # dark red
        ("#facc15", BLACK),  # yellow: white would fail AA
        ("#86efac", BLACK),  # light green
        ("#ffffff", BLACK),
        ("#000000", WHITE),
    ],
)
def test_picks_the_readable_foreground(color: str, foreground: str) -> None:
    assert readable_foreground(color) == foreground


def test_without_a_color_there_is_no_foreground() -> None:
    assert readable_foreground(None) is None


@pytest.mark.parametrize("step", [0x00, 0x33, 0x66, 0x76, 0x77, 0x99, 0xCC, 0xFF])
def test_the_chosen_foreground_always_passes_aa(step: int) -> None:
    """The worst case (a mid gray) still reaches ~4.58:1 with the better of the two."""
    for color in (f"#{step:02x}{step:02x}{step:02x}", f"#{step:02x}0000", f"#00{step:02x}00"):
        assert contrast_ratio(color, readable_foreground(color)) >= AA_CONTRAST
