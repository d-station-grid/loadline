"""振り返りの音声。セリフを声にする（tts）、置く・URL を出す・消す（Cloud Storage）。

web は音声の形式に依存させず、ここで出す URL を再生する。声を作れなくても振り返りは
作り、音声なし（文字だけ）にする。
"""

from typing import Protocol


class Voice(Protocol):
    """セリフを読み上げて WAV を返す。読めなければ None。adapter の tts が実体。"""

    async def speak(self, text: str) -> bytes | None: ...


class AudioStore(Protocol):
    """音声を置く場所。adapter の Cloud Storage が実体。"""

    async def put(self, path: str, wav: bytes) -> bool:
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


def review_audio_path(user_id: int, review_id: int) -> str:
    return f"{user_audio_prefix(user_id)}reviews/{review_id}.wav"
