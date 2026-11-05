type Props = {
  onSignIn: () => void;
  onGuest: () => void;
  /** ログインに失敗したときの文言 */
  error: string | null;
};

const STEPS = [
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
];

const VIEWS = [
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
];

const PROMISES = [
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
];

/** ログイン前のトップ。何ができるかを見せ、Google のログインかゲストへ進ませる */
export default function Landing({ onSignIn, onGuest, error }: Props) {
  const buttons = (
    <>
      <button type="button" className="primary" onClick={onSignIn}>
        Sign in with Google
      </button>
      <button type="button" onClick={onGuest}>
        Try as a guest
      </button>
    </>
  );
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <h1 className="logo">
            load<span>line</span>
          </h1>
        </div>
      </header>
      <main className="app-main landing">
        <section className="hero" aria-labelledby="hero-heading">
          <p className="eyebrow">For riders and runners with an Apple Watch</p>
          <h2 id="hero-heading">Your training, talked through once a week.</h2>
          <p className="lead">
            loadline turns the workouts on your Apple Watch into a dashboard of
            fitness, fatigue and VO2max. Once a week, an avatar walks you
            through what changed and offers a few ways to spend the next week.
            You choose.
          </p>
          <div className="actions">{buttons}</div>
          {error && <p role="alert">{error}</p>}
          <p className="muted small">
            No sign-up needed to try. The guest dashboard uses demo data.
          </p>
        </section>

        <section aria-labelledby="how-heading">
          <h2 id="how-heading">How it works</h2>
          <p className="muted">
            Set it up once. After that, your workouts arrive on their own.
          </p>
          <ol className="feature-grid">
            {STEPS.map((s, i) => (
              <li key={s.title} className="card">
                <span className="step">{i + 1}</span>
                <h3>{s.title}</h3>
                <p className="muted small">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="see-heading">
          <h2 id="see-heading">What you'll see</h2>
          <p className="muted">All on one screen.</p>
          <ul className="feature-grid">
            {VIEWS.map((v) => (
              <li key={v.title} className="card">
                <h3>{v.title}</h3>
                <p className="muted small">{v.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="data-heading">
          <h2 id="data-heading">Your data stays yours</h2>
          <p className="muted">
            Workouts and notes are health data. Here is what we promise.
          </p>
          <ul className="feature-grid promises">
            {PROMISES.map((p) => (
              <li key={p.title}>
                <h3>{p.title}</h3>
                <p className="muted small">{p.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <p className="card small disclaimer">
          <strong>Not medical advice.</strong> loadline shows your training data
          and suggests ways to spend your week. It does not diagnose, treat or
          judge pain, illness or injury. If something hurts or feels wrong, talk
          to a doctor.
        </p>
      </main>
    </>
  );
}
