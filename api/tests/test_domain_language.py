import pytest

from app.domain.language import Language, language_from_accept_language, language_from_browser


@pytest.mark.parametrize(
    ("tag", "language"),
    [
        ("ja", Language.JA),
        ("ja-JP", Language.JA),
        ("JA-jp", Language.JA),
        ("ja_JP", Language.JA),
        (" en-US ", Language.EN),
        ("en-GB", Language.EN),
        ("fr-FR", None),
        ("", None),
        (None, None),
    ],
)
def test_language_from_browser(tag: str | None, language: Language | None) -> None:
    assert language_from_browser(tag) is language


@pytest.mark.parametrize(
    ("header", "language"),
    [
        ("ja,en-US;q=0.9,en;q=0.8", Language.JA),
        ("ja-JP", Language.JA),
        ("en-US,en;q=0.9,ja;q=0.8", Language.EN),
        # 知らない言語は飛ばし、次に並ぶ知っている言語にする
        ("fr-FR,fr;q=0.9,ja;q=0.8", Language.JA),
        ("fr-FR,de;q=0.9", None),
        ("", None),
        (None, None),
    ],
)
def test_language_from_accept_language(header: str | None, language: Language | None) -> None:
    assert language_from_accept_language(header) == language
