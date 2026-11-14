import { useI18n } from "../i18n";

type Props = {
  onSignIn: () => void;
  onGuest: () => void;
  /** ログインに失敗したときの文言 */
  error: string | null;
};

/** ログイン前のトップ。何ができるかを見せ、Google のログインかゲストへ進ませる */
export default function Landing({ onSignIn, onGuest, error }: Props) {
  const { m } = useI18n();
  const t = m.landing;
  const buttons = (
    <>
      <button type="button" className="primary" onClick={onSignIn}>
        {t.signIn}
      </button>
      <button type="button" onClick={onGuest}>
        {t.tryAsGuest}
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
          <p className="eyebrow">{t.eyebrow}</p>
          <h2 id="hero-heading">{t.heading}</h2>
          <p className="lead">{t.lead}</p>
          <div className="actions">{buttons}</div>
          {error && <p role="alert">{error}</p>}
          <p className="muted small">{t.noSignUp}</p>
        </section>

        <section aria-labelledby="how-heading">
          <h2 id="how-heading">{t.howHeading}</h2>
          <p className="muted">{t.howLead}</p>
          <ol className="feature-grid">
            {t.steps.map((s, i) => (
              <li key={s.title} className="card">
                <span className="step">{i + 1}</span>
                <h3>{s.title}</h3>
                <p className="muted small">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="see-heading">
          <h2 id="see-heading">{t.seeHeading}</h2>
          <p className="muted">{t.seeLead}</p>
          <ul className="feature-grid">
            {t.views.map((v) => (
              <li key={v.title} className="card">
                <h3>{v.title}</h3>
                <p className="muted small">{v.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="data-heading">
          <h2 id="data-heading">{t.dataHeading}</h2>
          <p className="muted">{t.dataLead}</p>
          <ul className="feature-grid promises">
            {t.promises.map((p) => (
              <li key={p.title}>
                <h3>{p.title}</h3>
                <p className="muted small">{p.body}</p>
              </li>
            ))}
          </ul>
        </section>

        <p className="card small disclaimer">
          <strong>{t.disclaimerTitle}</strong> {t.disclaimer}
        </p>
      </main>
    </>
  );
}
