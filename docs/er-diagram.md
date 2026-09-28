# ER 図

```mermaid
erDiagram
  users ||--o{ ingest_tokens : ""
  users ||--o{ workouts : ""
  workouts ||--o{ workout_heart_rates : ""
  users ||--o{ vo2max_readings : ""
  users ||--o{ notes : ""
  users ||--o{ weekly_reviews : ""
  weekly_reviews ||--o{ weekly_review_options : ""

  users {
    bigint id PK
    varchar firebase_uid UK "デモ用の行は NULL"
    varchar email
    boolean is_demo "ゲストに見せるデモデータの持ち主"
    integer max_heart_rate
    integer resting_heart_rate
    integer zone_boundary_1 "Low と Mid の境目"
    integer zone_boundary_2 "Mid と High の境目"
    varchar timezone "例 Asia/Tokyo"
    smallint review_weekday "0 が月曜、6 が日曜"
    boolean send_notes_to_ai
    timestamptz created_at
    timestamptz updated_at
  }
  ingest_tokens {
    bigint id PK
    bigint user_id FK
    varchar token_digest UK "ハッシュだけを保存"
    varchar last_four "マスク表示用"
    timestamptz last_used_at
    timestamptz revoked_at "再発行で無効にした日時"
    timestamptz created_at
  }
  workouts {
    bigint id PK
    bigint user_id FK
    varchar external_id "Health Auto Export の id"
    varchar sport "ride か run"
    timestamptz started_at
    timestamptz ended_at
    integer duration_sec
    integer avg_heart_rate
    integer max_heart_rate
    timestamptz created_at
    timestamptz updated_at
  }
  workout_heart_rates {
    bigint id PK
    bigint workout_id FK
    timestamptz recorded_at "1分ごと"
    integer min_bpm
    integer avg_bpm
    integer max_bpm
  }
  vo2max_readings {
    bigint id PK
    bigint user_id FK
    timestamptz measured_at
    numeric value "小数1桁 例 45.7"
    timestamptz created_at
  }
  notes {
    bigint id PK
    bigint user_id FK
    date date
    varchar(12) label "チャートに出す短いラベル"
    text body
    timestamptz created_at
    timestamptz updated_at
  }
  weekly_reviews {
    bigint id PK
    bigint user_id FK
    date period_start
    date period_end
    varchar situation "コードで判定した状況"
    text script "セリフ。字幕にも使う"
    varchar audio_path "Cloud Storage 上の音声"
    varchar status "生成中、完了、失敗"
    boolean is_fallback "定型のセリフか"
    timestamptz created_at
    timestamptz updated_at
  }
  weekly_review_options {
    bigint id PK
    bigint weekly_review_id FK
    smallint position
    varchar label
    varchar description
    timestamptz selected_at "選んだものだけに入る"
  }
```

## 一意制約

| テーブル | カラム | 理由 |
|---|---|---|
| users | firebase_uid | Google アカウント1つにつき、利用者は1人 |
| ingest_tokens | token_digest | トークンから利用者を特定する |
| workouts | user_id, external_id | 同じ記録が何度届いても、二重に数えない |
| vo2max_readings | user_id, measured_at | 同じ測定が何度届いても、二重に数えない |
| notes | user_id, date | メモは1日1件 |
| weekly_reviews | user_id, period_start | 同じ期間の振り返りを、二重に作らない |

## 保存しない値

負荷、体力、疲労、余力、強度ごとの時間は、保存しません。`workout_heart_rates` の1分ごとの心拍と、`users` の心拍の設定から、表示のたびに計算します。心拍の設定を変えても、過去の記録を計算し直す処理は要りません。

メモとワークアウトは、外部キーでつなぎません。ワークアウト詳細に出す「その日のメモ」は、利用者のタイムゾーンでの日付で探します。

## ゲストのデータ

ゲストログインでは、`is_demo` の利用者1人ぶんのデモデータを、ゲスト全員で共有します。ゲストができるのは閲覧だけです。メモの保存、設定の変更、トークンの発行、選択肢の保存、アカウントの削除はできません。振り返りのセリフと音声は、デモ用に作っておいたものを流します。
