"""画面と週次レビューの言語。

今は英語と日本語の 2 つ。既定は英語（英語版を先に作ったため）。
初回ログインでは、ブラウザの言語（navigator.language の "ja-JP" など）から決める。
"""

from enum import StrEnum


class Language(StrEnum):
    EN = "en"
    JA = "ja"


DEFAULT_LANGUAGE = Language.EN


def language_from_browser(tag: str | None) -> Language | None:
    """ブラウザの言語タグ（"ja-JP"、"en-US" など）から言語を決める。知らない言語なら None。

    地域の部分（-JP、-US）は見ない。大文字と小文字も区別しない。
    """
    if not tag:
        return None
    primary = tag.strip().split("-")[0].split("_")[0].lower()
    try:
        return Language(primary)
    except ValueError:
        return None
