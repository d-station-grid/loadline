"""週次レビューの音声。セリフを声にする（言語ごとの声）、置く・URL を出す・消す（Cloud Storage）。

声は言語で替える。英語は tts（Kokoro、WAV）、日本語は Google Cloud Text-to-Speech（MP3）。
web は音声の形式に依存させず、ここで出す URL を再生する。形式は置くときの Content-Type と
拡張子にだけ使う。声を作れなくても週次レビューは作り、音声なし（文字だけ）にする。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.domain.language import Language


@dataclass(frozen=True)
class AudioFormat:
    """音声の形式。置くときの Content-Type と、置き場所の拡張子。"""

    content_type: str
    extension: str


WAV = AudioFormat("audio/wav", "wav")
MP3 = AudioFormat("audio/mpeg", "mp3")


@dataclass(frozen=True)
class Speech:
    """読み上げた音声と、その形式。"""

    data: bytes
    format: AudioFormat


class Speaker(Protocol):
    """1 つの言語の声。セリフを読み上げた音声を返す。読めなければ None。
    adapter の tts（英語）と Google の Text-to-Speech（日本語）が実体。"""

    async def speak(self, text: str) -> bytes | None: ...


class Voice(Protocol):
    """セリフを、その言語の声で読み上げる。声のない言語や、読めなければ None。"""

    async def speak(self, text: str, language: Language) -> Speech | None: ...


class VoicesByLanguage:
    """言語ごとの声をまとめて、Voice として使う。"""

    def __init__(self, speakers: Mapping[Language, tuple[Speaker, AudioFormat]]) -> None:
        self._speakers = dict(speakers)

    async def speak(self, text: str, language: Language) -> Speech | None:
        found = self._speakers.get(language)
        if found is None:
            return None
        speaker, audio_format = found
        data = await speaker.speak(text)
        return None if data is None else Speech(data, audio_format)


def voices(english: Speaker | None, japanese: Speaker | None) -> VoicesByLanguage | None:
    """英語の声（WAV）と日本語の声（MP3）をまとめる。どちらもなければ None（声にしない）。"""
    speakers: dict[Language, tuple[Speaker, AudioFormat]] = {}
    if english is not None:
        speakers[Language.EN] = (english, WAV)
    if japanese is not None:
        speakers[Language.JA] = (japanese, MP3)
    return VoicesByLanguage(speakers) if speakers else None


class AudioStore(Protocol):
    """音声を置く場所。adapter の Cloud Storage が実体。"""

    async def put(self, path: str, data: bytes, content_type: str) -> bool:
        """置けたら True。置けなければ False（呼ぶ側は音声なしにする）。"""
        ...

    async def url(self, path: str) -> str | None:
        """期限つきで再生できる URL。出せなければ None。"""
        ...

    async def delete_all(self, prefix: str) -> None:
        """prefix で始まる音声をすべて消す。消せなければ AccountDeleteError を上げる。"""
        ...


def user_audio_prefix(user_id: int) -> str:
    """その利用者の音声がすべて入る場所。アカウントを消すときに、ここを丸ごと消す。"""
    return f"users/{user_id}/"


def review_audio_path(user_id: int, review_id: int, audio_format: AudioFormat = WAV) -> str:
    return f"{user_audio_prefix(user_id)}reviews/{review_id}.{audio_format.extension}"
