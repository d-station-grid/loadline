# loadline

Apple Watch の記録を取り込み、アバターが声で振り返りを話すダッシュボード。RUNTEQ の卒業制作。

## 資料の地図

- `README.md`: 企画、機能、技術スタック、開発手順
- `docs/er-diagram.md`: ER 図（Mermaid）
- 画面遷移図: README の 11 章にある Figma

## 破ってはいけない判断

- Jev で確認できなかったセリフは話さない。定型に切り替える
- 数値や日付の比較はコードでやる。LLM に任せない
- 取り込むのは Apple Watch の記録だけ
- 音声はファイルに保存して URL を再生する。web を音声の形式（WAV、24kHz）に依存させない。声の生成は後で替える

## 検査コマンド（ルートで）

- `make check`: api（ruff、mypy、pytest）、web（typecheck、lint、format、vitest）、tts（ruff）
- `make fmt`: 整形
- `make types`: OpenAPI から web の型を生成。api の schema を変えたら必ず実行し、生成物もコミットする
- `make dev`: api と web を起動
