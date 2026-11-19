# 画面遷移図

矢印の横の文字は、押すボタンや、画面が切り替わる条件です。

```mermaid
flowchart LR
  subgraph before["ログイン前"]
    top["トップ"]
    google(["Google のログイン（外部）"])
  end

  subgraph setup["設定"]
    guide["導入の案内"]
    settings["設定"]
    confirm["アカウント削除の確認"]
  end

  subgraph view["閲覧"]
    dashboard["ダッシュボード<br>アバターと週次レビュー"]
    note["メモ（モーダル）"]
    workouts["ワークアウト一覧"]
    workout["ワークアウト詳細"]
  end

  top -->|"Google でログイン"| google
  top -->|"ゲストで試す（デモデータ）"| dashboard
  google -->|"記録がまだ届いていない"| guide
  google -->|"記録が届いている"| dashboard

  guide -->|"あとで設定する／ダッシュボードへ"| dashboard
  settings -->|"設定の案内を開く"| guide
  settings -->|"アカウントを削除…"| confirm
  confirm -->|"キャンセル"| settings
  confirm -->|"アカウントを削除する（ログアウトしてトップへ）"| top

  dashboard -->|"+ メモ／チャートの日付"| note
  note -->|"閉じる"| dashboard
  dashboard -->|"すべてのワークアウト ›"| workouts
  dashboard -->|"最近のワークアウトの行"| workout
  dashboard -->|"設定を開く（心拍が未設定のとき）"| settings
  workouts -->|"行を押す"| workout
  workout -->|"‹ ワークアウト"| workouts
```

## ヘッダー

ログインのあとは、どの画面にもヘッダーがあります。ヘッダーの「ダッシュボード」「ワークアウト」「設定」で、それぞれの画面に移れます。「ログアウト」を押すと、トップに戻ります。図では、ヘッダーからの矢印を省いています。

## ゲストにできないこと

ゲストは、デモデータを見るだけです。

| 画面 | ゲストのとき |
|---|---|
| 導入の案内 | 開けない |
| 設定 | 見られるが、変更はできない |
| アカウント削除の確認 | 開けない |
| ダッシュボード | 週次レビューの作成と、選択肢を選ぶことはできない |
| メモ | 読めるが、書けない |
