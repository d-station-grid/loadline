"""言語ごとの声をまとめる VoicesByLanguage と、音声の置き場所。"""

from app.domain.language import Language
from app.services.audio import MP3, WAV, Speech, review_audio_path, voices


class FakeSpeaker:
    def __init__(self, data: bytes | None) -> None:
        self.data = data
        self.spoken: list[str] = []

    async def speak(self, text: str) -> bytes | None:
        self.spoken.append(text)
        return self.data


async def test_each_language_uses_its_own_voice_and_format() -> None:
    english, japanese = FakeSpeaker(b"RIFF"), FakeSpeaker(b"ID3")
    voice = voices(english, japanese)
    assert voice is not None

    assert await voice.speak("A steady week.", Language.EN) == Speech(b"RIFF", WAV)
    assert await voice.speak("安定した週でした。", Language.JA) == Speech(b"ID3", MP3)
    assert english.spoken == ["A steady week."]
    assert japanese.spoken == ["安定した週でした。"]


async def test_a_language_without_a_voice_is_not_voiced() -> None:
    english = FakeSpeaker(b"RIFF")
    voice = voices(english, None)
    assert voice is not None

    assert await voice.speak("安定した週でした。", Language.JA) is None
    assert english.spoken == []


async def test_a_voice_that_cannot_speak_gives_none() -> None:
    voice = voices(None, FakeSpeaker(None))
    assert voice is not None

    assert await voice.speak("安定した週でした。", Language.JA) is None


def test_no_voices_means_none() -> None:
    assert voices(None, None) is None


def test_the_path_has_the_extension_of_the_format() -> None:
    assert review_audio_path(1, 2) == "users/1/reviews/2.wav"
    assert review_audio_path(1, 2, MP3) == "users/1/reviews/2.mp3"
