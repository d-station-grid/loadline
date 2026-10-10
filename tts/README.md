# tts

Kokoro（kokoro-onnx）で英語のセリフを WAV にする Cloud Run 用のサービス。

- `POST /speak` に `{"text": "..."}` を送ると `audio/wav` が返る
- `GET /health` はモデルを読み込まずに応答する

## モデルのファイル

Git には入れていない。次の 2 つを kokoro-onnx の GitHub Releases（`model-files-v1.0`）から取り、このディレクトリに置く。

```sh
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

| ファイル | 大きさ |
|---|---|
| `kokoro-v1.0.onnx` | 約 326MB |
| `voices-v1.0.bin` | 約 28MB |

## 手元で動かす

```sh
uv run uvicorn main:app --reload --port 8081
curl -X POST localhost:8081/speak -H 'content-type: application/json' -d '{"text": "Hello."}' -o hello.wav
```

## 点検

```sh
uv run ruff check . && uv run ruff format --check .
```
