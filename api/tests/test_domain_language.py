import pytest

from app.domain.language import Language, language_from_browser


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
