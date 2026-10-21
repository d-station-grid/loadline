import pytest

from app.domain.label import MAX_LABEL_WIDTH, display_width


# web の lib/label.test.ts と同じ例。数え方がずれないように
@pytest.mark.parametrize(
    ("text", "width"),
    [
        ("Race", 4),
        ("大会", 4),
        ("5km走", 5),
        ("ｱｲｳ", 3),  # 半角カタカナは 1
        ("ＡＢ", 4),  # 全角英数字は 2
        ("😷", 2),
        ("①α", 2),  # 環境で幅が変わる文字は 1
        ("", 0),
    ],
)
def test_display_width_counts_full_width_as_two(text: str, width: int) -> None:
    assert display_width(text) == width


def test_max_width_fits_12_half_or_6_full() -> None:
    assert display_width("x" * 12) == MAX_LABEL_WIDTH
    assert display_width("あ" * 6) == MAX_LABEL_WIDTH
