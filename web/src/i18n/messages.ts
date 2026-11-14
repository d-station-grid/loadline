import type { Form } from "../api";

/**
 * 画面の文言。英語（en）を正本にし、日本語（ja）は同じ形で書く。
 * ja は Messages の型で書くので、項目が抜けていれば型のエラーになる。
 * 数や日付が入る文言は関数にする（語順が言語で違うため）。
 *
 * 今は、ログイン前のトップ、ヘッダー、ダッシュボード、週次レビューの吹き出しだけ。
 * 設定、ワークアウト、メモの画面は、次の PR で足す。
 */
export const en = {
  common: {
    loading: "Loading…",
    retry: "Retry",
    somethingWentWrong: "Something went wrong",
    openSettings: "Open settings",
    close: "Close",
  },
  app: {
    signInFailed: "Sign-in failed",
    guestUnavailable: "Guest mode isn't available right now.",
    loggingOut: "Logging out…",
    logoutFailed: "Couldn't log out. Please try again.",
    logOut: "Log out",
    navLabel: "Main",
    nav: { dashboard: "Dashboard", workouts: "Workouts", settings: "Settings" },
    guestBanner: "Viewing demo data as a guest (read-only)",
  },
  landing: {
    signIn: "Sign in with Google",
    tryAsGuest: "Try as a guest",
    eyebrow: "For riders and runners with an Apple Watch",
    heading: "Your training, talked through once a week.",
    lead: "loadline turns the workouts on your Apple Watch into a dashboard of fitness, fatigue and VO2max. Once a week, an avatar walks you through what changed and offers a few ways to spend the next week. You choose.",
    noSignUp: "No sign-up needed to try. The guest dashboard uses demo data.",
    howHeading: "How it works",
    howLead: "Set it up once. After that, your workouts arrive on their own.",
    steps: [
      {
        title: "Record with your Apple Watch",
        body: "Rides and runs, as you already do. loadline reads heart rate minute by minute, and VO2max when your watch updates it.",
      },
      {
        title: "Your iPhone sends them",
        body: "Health Auto Export sends new workouts to loadline on its own. We guide you through the one-time setup.",
      },
      {
        title: "Once a week, a short talk",
        body: "On the day you pick, the avatar talks through your last few weeks, then offers two or three options. Next week, you look at how it went together.",
      },
    ],
    seeHeading: "What you'll see",
    seeLead: "All on one screen.",
    views: [
      {
        title: "Fitness, fatigue and daily load",
        body: "How much you've built up, how tired you are, and what each day added.",
      },
      {
        title: "VO2max",
        body: "Each reading from your watch, with a 30-day average so a single value doesn't swing the picture.",
      },
      {
        title: "Where your time went",
        body: "Minutes in Low, Mid and High for rides and runs, and how hard each workout was.",
      },
    ],
    dataHeading: "Your data stays yours",
    dataLead: "Workouts and notes are health data. Here is what we promise.",
    promises: [
      {
        title: "Delete everything, any time",
        body: "One button in Settings removes your workouts, notes, reviews and your account.",
      },
      {
        title: "Keep your notes away from AI",
        body: "Turn off “Let the AI read my notes” in Settings and your weekly review is made from numbers only.",
      },
      {
        title: "No name, no email to AI",
        body: "Only your numbers and notes are sent to write the review. Never your name or email.",
      },
    ],
    disclaimerTitle: "Not medical advice.",
    disclaimer:
      "loadline shows your training data and suggests ways to spend your week. It does not diagnose, treat or judge pain, illness or injury. If something hurts or feels wrong, talk to a doctor.",
  },
  sports: { all: "All", ride: "Ride", run: "Run" } as Record<string, string>,
  ranges: {
    "1w": { label: "1W", last: "last week", prev: "prev week" },
    "1m": { label: "1M", last: "last month", prev: "prev month" },
    "3m": { label: "3M", last: "last 3 months", prev: "prev 3 months" },
    "6m": { label: "6M", last: "last 6 months", prev: "prev 6 months" },
  },
  /** Form の一言。fresh は「疲労が抜けている」とだけ言い、練習が順調だとは読めない言い方にする */
  form: {
    fatigued: "Tired — ease off",
    fresh: "Fresh — fatigue has cleared",
    steady: "Balanced",
    not_enough_data: "Not enough data to judge",
  } as Record<Form, string>,
  duration: {
    lessThanMinute: "<1m",
    hoursMinutes: (h: number, m: string) => `${h}h ${m}m`,
    minutes: (m: number) => `${m}m`,
    hoursUnit: "h",
  },
  dashboard: {
    heading: "Dashboard",
    lastReceived: (when: string) => `Last received · ${when}`,
    period: "Period",
    addNote: "+ Note",
    latest: "Latest",
    fitness: "Fitness",
    fatigue: "Fatigue",
    form: "Form",
    vo2max: "VO2max",
    vsLastWeek: (change: string) => `${change} vs last week`,
    vo2maxSince: (change: string, since: string, day: string) =>
      `${change} since ${since} · ${day}`,
    trendHeading: "Fitness, fatigue and VO2max",
    needsHeartRate: "Set your max and resting heart rate to see training load.",
    trendHelp:
      "Click a day to add a note. Notes with a label show on the chart. Fitness and fatigue include every sport.",
    noVo2max: "No VO2max in this period.",
    daysWithoutHeartRate: (n: number) =>
      `▲ marks ${n} day(s) with a workout that has no heart rate. Their load counts as 0, so fitness and fatigue read low.`,
    intensity: "Intensity",
    intensitySport: "Intensity sport",
    intensityPeriod: "Intensity period",
    intensitySummary: (sport: string, last: string, workouts: number) =>
      `${sport} · ${last} · ${workouts}`,
    noWorkoutsInPeriod: "No workouts in this period.",
    zoneMinutesByWeek: "Minutes in each zone · by week",
    weeksWithoutZones: (n: number) =>
      `▲ marks ${n} week(s) with a workout that has no heart rate. Its minutes are left out.`,
    needsBoundaries: "Needs zone boundaries in settings.",
    loadAndHigh: "Load and time in High",
    needsBoundariesAndHeartRate:
      "Needs zone boundaries in settings and heart rate on the workouts.",
    timeInZone: "Time in each zone",
    workoutsWithoutZones: (n: number) =>
      `Not shown: ${n} workout(s) in this period have no heart rate.`,
    totals: "Totals",
    time: "Time",
    workouts: "Workouts",
    load: "Load",
    loadPerWorkout: "Load per workout",
    loadLeavesOut: (now: number, prev: number) =>
      `Load leaves out workouts without heart rate: ${now} in this period, ${prev} in the previous one.`,
    recentHeading: "Recent workouts",
    seeAll: "See all workouts ›",
    noWorkoutsYet: "No workouts yet.",
    date: "Date",
    sport: "Sport",
    avgHr: "Avg HR",
    outsidePeriod: "Outside the dashboard period",
    noHeartRateTitle: "No heart rate, so load can't be computed",
    noHr: "No HR",
  },
  review: {
    toggle: "💬 This week's review",
    heading: "This week's review",
    voice: "Review voice",
    play: "▶ Play",
    pause: "❚❚ Pause",
    replay: "↻ Replay",
    hide: "– Hide",
    noReviewYet: "No review for this week yet.",
    writing: "Writing your review…",
    create: "Create this week's review",
    createHint: "This usually takes 20–30 seconds.",
    needsSettings:
      "Set your max and resting heart rate before creating a review.",
    guestCannotCreate: "Guests can't create reviews.",
    weekReviewed: (from: string, to: string) =>
      `Week reviewed: ${from} – ${to}`,
    question: "How will you spend the week ahead?",
    guestCannotChoose:
      "Guests can't choose an option. Sign in to plan your week.",
    pastWeek: "This review is from a past week.",
    loadThisWeek: "Load this week's review",
    hideText: "💬 Hide text",
    showText: "💬 Show text",
  },
};

export type Messages = typeof en;

export const ja: Messages = {
  common: {
    loading: "読み込み中…",
    retry: "再試行",
    somethingWentWrong: "問題が発生しました",
    openSettings: "設定を開く",
    close: "閉じる",
  },
  app: {
    signInFailed: "ログインできませんでした",
    guestUnavailable: "今はゲストで使えません。",
    loggingOut: "ログアウトしています…",
    logoutFailed: "ログアウトできませんでした。もう一度お試しください。",
    logOut: "ログアウト",
    navLabel: "メイン",
    nav: {
      dashboard: "ダッシュボード",
      workouts: "ワークアウト",
      settings: "設定",
    },
    guestBanner: "ゲストとしてデモデータを表示しています（閲覧のみ）",
  },
  landing: {
    signIn: "Google でログイン",
    tryAsGuest: "ゲストで試す",
    eyebrow: "Apple Watch で走る・漕ぐ人のために",
    heading: "週に 1 回、トレーニングを振り返って話します。",
    lead: "loadline は、Apple Watch のワークアウトを、体力・疲労・VO2max のダッシュボードにします。週に 1 回、アバターが変化を話し、次の 1 週間の過ごし方をいくつか提案します。選ぶのはあなたです。",
    noSignUp:
      "登録しなくても試せます。ゲストのダッシュボードはデモデータです。",
    howHeading: "使い方",
    howLead: "最初に 1 回設定すれば、あとはワークアウトが自動で届きます。",
    steps: [
      {
        title: "Apple Watch で記録する",
        body: "いつもどおりライドやランを記録するだけです。loadline は 1 分ごとの心拍数と、時計が更新した VO2max を読み取ります。",
      },
      {
        title: "iPhone が送る",
        body: "Health Auto Export が、新しいワークアウトを loadline に自動で送ります。最初の設定は案内します。",
      },
      {
        title: "週に 1 回、短い話",
        body: "選んだ曜日に、アバターがこの数週間を振り返って話し、2〜3 個の選択肢を出します。次の週に、どうだったかを一緒に確かめます。",
      },
    ],
    seeHeading: "見られるもの",
    seeLead: "すべて 1 つの画面で。",
    views: [
      {
        title: "体力・疲労・日ごとの負荷",
        body: "どれだけ積み上げたか、どれだけ疲れているか、その日に何が加わったか。",
      },
      {
        title: "VO2max",
        body: "時計の測定ごとの値と、30 日の平均。1 回の値で印象が揺れないようにしています。",
      },
      {
        title: "時間の使い方",
        body: "ライドとランの低・中・高の強度ごとの時間と、1 回ごとのきつさ。",
      },
    ],
    dataHeading: "データはあなたのもの",
    dataLead: "ワークアウトとメモは健康のデータです。次のことを約束します。",
    promises: [
      {
        title: "いつでもすべて削除できる",
        body: "設定のボタン 1 つで、ワークアウト、メモ、週次レビュー、アカウントを削除します。",
      },
      {
        title: "メモを AI に読ませない",
        body: "設定の「Let the AI read my notes」をオフにすると、週次レビューは数字だけで作成します。",
      },
      {
        title: "名前もメールアドレスも AI に送らない",
        body: "週次レビューの作成に送るのは、数字とメモだけです。名前やメールアドレスは送りません。",
      },
    ],
    disclaimerTitle: "医療の助言ではありません。",
    disclaimer:
      "loadline は、トレーニングのデータを表示し、1 週間の過ごし方を提案します。痛み、病気、けがの診断、治療、判断はしません。痛みや違和感があるときは、医師に相談してください。",
  },
  sports: { all: "すべて", ride: "ライド", run: "ラン" },
  ranges: {
    "1w": { label: "1週", last: "直近 1 週間", prev: "前の 1 週間" },
    "1m": { label: "1か月", last: "直近 1 か月", prev: "前の 1 か月" },
    "3m": { label: "3か月", last: "直近 3 か月", prev: "前の 3 か月" },
    "6m": { label: "6か月", last: "直近 6 か月", prev: "前の 6 か月" },
  },
  form: {
    fatigued: "疲れ気味 — 控えめに",
    fresh: "疲労が抜けている",
    steady: "釣り合っている",
    not_enough_data: "判断できるだけの記録がない",
  },
  duration: {
    lessThanMinute: "1分未満",
    hoursMinutes: (h, m) => `${h}時間${m}分`,
    minutes: (m) => `${m}分`,
    hoursUnit: "時間",
  },
  dashboard: {
    heading: "ダッシュボード",
    lastReceived: (when) => `最後の受信 · ${when}`,
    period: "期間",
    addNote: "+ メモ",
    latest: "最新",
    fitness: "体力",
    fatigue: "疲労",
    form: "余力",
    vo2max: "VO2max",
    vsLastWeek: (change) => `1 週間前から ${change}`,
    vo2maxSince: (change, since, day) => `${since} から ${change} · ${day}`,
    trendHeading: "体力・疲労・VO2max",
    needsHeartRate:
      "負荷を表示するには、最大心拍数と安静時心拍数を設定してください。",
    trendHelp:
      "日付を押すとメモを書けます。ラベルのあるメモはグラフに表示されます。体力と疲労は全種目で計算しています。",
    noVo2max: "この期間に VO2max の記録はありません。",
    daysWithoutHeartRate: (n) =>
      `▲ は、心拍数のないワークアウトがあった ${n} 日です。その日の負荷は 0 として計算するので、体力と疲労は低めに出ます。`,
    intensity: "強度",
    intensitySport: "強度の種目",
    intensityPeriod: "強度の期間",
    intensitySummary: (sport, last, workouts) =>
      `${sport} · ${last} · ${workouts} 回`,
    noWorkoutsInPeriod: "この期間にワークアウトはありません。",
    zoneMinutesByWeek: "強度ごとの時間（分）· 週ごと",
    weeksWithoutZones: (n) =>
      `▲ は、心拍数のないワークアウトがあった ${n} 週です。その回の時間は含めていません。`,
    needsBoundaries: "設定で強度の境目を入れてください。",
    loadAndHigh: "負荷と高強度の時間",
    needsBoundariesAndHeartRate:
      "設定の強度の境目と、ワークアウトの心拍数が必要です。",
    timeInZone: "強度ごとの時間",
    workoutsWithoutZones: (n) =>
      `表示していません。この期間の ${n} 回のワークアウトに心拍数がありません。`,
    totals: "合計",
    time: "時間",
    workouts: "回数",
    load: "負荷",
    loadPerWorkout: "1 回あたりの負荷",
    loadLeavesOut: (now, prev) =>
      `負荷には、心拍数のないワークアウトを含めていません（この期間 ${now} 回、前の期間 ${prev} 回）。`,
    recentHeading: "最近のワークアウト",
    seeAll: "すべてのワークアウト ›",
    noWorkoutsYet: "まだワークアウトがありません。",
    date: "日時",
    sport: "種目",
    avgHr: "平均心拍",
    outsidePeriod: "ダッシュボードの期間の外",
    noHeartRateTitle: "心拍数がないので、負荷を計算できません",
    noHr: "心拍なし",
  },
  review: {
    toggle: "💬 今週の週次レビュー",
    heading: "今週の週次レビュー",
    voice: "週次レビューの音声",
    play: "▶ 再生",
    pause: "❚❚ 一時停止",
    replay: "↻ もう一度",
    hide: "– 隠す",
    noReviewYet: "今週の週次レビューはまだありません。",
    writing: "週次レビューを作成しています…",
    create: "今週の週次レビューを作成",
    createHint: "ふだんは 20〜30 秒かかります。",
    needsSettings:
      "週次レビューを作成するには、最大心拍数と安静時心拍数を設定してください。",
    guestCannotCreate: "ゲストは週次レビューを作成できません。",
    weekReviewed: (from, to) => `対象の週: ${from} – ${to}`,
    question: "次の 1 週間を、どう過ごしますか？",
    guestCannotChoose:
      "ゲストは選択肢を選べません。ログインすると、1 週間の過ごし方を選べます。",
    pastWeek: "これは過ぎた週の週次レビューです。",
    loadThisWeek: "今週の週次レビューを読み込む",
    hideText: "💬 文字を隠す",
    showText: "💬 文字を表示",
  },
};
