"""web が使う「全角・幅広の文字」の範囲を、api と同じ Unicode の表から書き出す。

ラベルの幅は api（app/domain/label.py）と web（src/lib/label.ts）の両方で数える。
web は Unicode の表を持たないので、ここで範囲の一覧を作って渡す。
api の Python を上げて Unicode の版が変わったら、もう一度実行する（テストが古さを知らせる）。

    cd api && uv run python -m scripts.export_label_widths
"""

import sys
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "label-widths.gen.ts"


def wide_ranges() -> list[tuple[int, int]]:
    """全角（F）と幅広（W）の範囲。間の未割り当ての文字はつないで、一覧を短くする。"""
    ranges: list[list[int]] = []
    for code in range(sys.maxunicode + 1):
        ch = chr(code)
        if unicodedata.category(ch) == "Cn":
            continue
        if unicodedata.east_asian_width(ch) not in ("F", "W"):
            continue
        if ranges and all(
            unicodedata.category(chr(c)) == "Cn" for c in range(ranges[-1][1] + 1, code)
        ):
            ranges[-1][1] = code
        else:
            ranges.append([code, code])
    return [(a, b) for a, b in ranges]


def render() -> str:
    lines = [
        "// 生成したファイル。手で直さない。",
        "// api の scripts/export_label_widths.py が、"
        f"Unicode {unicodedata.unidata_version} の表から書き出した。",
        "",
        "/** East Asian Width が全角（F）か幅広（W）の文字の範囲（両端を含む） */",
        "export const WIDE_RANGES: readonly (readonly [number, number])[] = [",
        *(f"  [0x{a:x}, 0x{b:x}]," for a, b in wide_ranges()),
        "];",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUT.write_text(render())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
