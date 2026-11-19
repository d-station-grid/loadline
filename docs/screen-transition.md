# 画面遷移図

矢印の横の文字は、押すボタンや、画面が切り替わる条件です。

```mermaid
flowchart TD
  top["#nbsp;#nbsp;#nbsp;トップ#nbsp;#nbsp;#nbsp;"]
  google(["#nbsp;#nbsp;#nbsp;Google のログイン（外部）#nbsp;#nbsp;#nbsp;"])
  guide["#nbsp;#nbsp;#nbsp;導入の案内#nbsp;#nbsp;#nbsp;"]
  dashboard["#nbsp;#nbsp;#nbsp;ダッシュボード#nbsp;#nbsp;#nbsp;<br>#nbsp;#nbsp;#nbsp;アバターと週次レビュー#nbsp;#nbsp;#nbsp;"]
  note["#nbsp;#nbsp;#nbsp;メモ（モーダル）#nbsp;#nbsp;#nbsp;"]
  workouts["#nbsp;#nbsp;#nbsp;ワークアウト一覧#nbsp;#nbsp;#nbsp;"]
  workout["#nbsp;#nbsp;#nbsp;ワークアウト詳細#nbsp;#nbsp;#nbsp;"]
  settings["#nbsp;#nbsp;#nbsp;設定#nbsp;#nbsp;#nbsp;"]
  confirm["#nbsp;#nbsp;#nbsp;アカウント削除の確認#nbsp;#nbsp;#nbsp;"]
  bye(["#nbsp;#nbsp;#nbsp;トップへ#nbsp;#nbsp;#nbsp;"])

  top -->|"Google でログイン"| google
  top -->|"ゲストで試す"| dashboard
  google -->|"初回"| guide
  google -->|"2 回目以降"| dashboard
  guide -->|"あとで設定する"| dashboard

  dashboard -->|"+ メモ"| note
  note -->|"閉じる"| dashboard
  dashboard -->|"すべてのワークアウト"| workouts
  dashboard -->|"最近の行"| workout
  workouts -->|"行"| workout
  workout -->|"戻る"| workouts

  dashboard -->|"設定を開く"| settings
  settings -->|"案内を開く"| guide
  settings -->|"削除…"| confirm
  confirm -->|"キャンセル"| settings
  confirm -->|"削除する"| bye

  classDef before fill:#eef2f4,stroke:#8a9aa3
  classDef setup fill:#e8f0fb,stroke:#5b7fb5
  classDef view fill:#e6f4f2,stroke:#2f8a80
  class top,google,bye before
  class guide,settings,confirm setup
  class dashboard,note,workouts,workout view
```

色は、灰がログイン前、青が設定、緑が閲覧の画面です。

## 矢印の補足

- **初回**: Google でログインしたとき、記録がまだ一度も届いていなければ、導入の案内を出します。届いていれば、ダッシュボードを出します
- **ゲストで試す**: デモデータのダッシュボードに入ります
- **あとで設定する**: 最初の記録が届いたあとは、「ダッシュボードへ」でも移れます
- **+ メモ**: チャートの日付を押しても開きます
- **最近の行**: ダッシュボードの「最近のワークアウト」の行です
- **設定を開く**: 心拍がまだ入っていないとき、ダッシュボードに出ます。ふだんはヘッダーの「設定」から開きます
- **案内を開く**: 設定の画面の「設定の案内を開く」です
- **削除する**: アカウントとデータを消し、ログアウトしてトップに戻ります

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
