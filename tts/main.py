"""Kokoro で英語のセリフを読み上げる、最小の FastAPI。

  POST /speak {"text": "..."}  → WAV を返す
  GET  /health                 → モデルを読み込まずに返す

モデルは最初の /speak で読み込む（起動を速くするため）。
"""

import io
import wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Response
from pydantic import BaseModel

HERE = Path(__file__).parent
MODEL = HERE / "kokoro-v1.0.onnx"
VOICES = HERE / "voices-v1.0.bin"

app = FastAPI()
_kokoro = None


def kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        _kokoro = Kokoro(str(MODEL), str(VOICES))
    return _kokoro


class Line(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _kokoro is not None}


@app.post("/speak")
def speak(line: Line):
    samples, rate = kokoro().create(line.text, voice="af_heart", speed=0.95, lang="en-us")

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())

    return Response(content=buffer.getvalue(), media_type="audio/wav")
