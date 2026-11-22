# loadline

[日本語](README.md)

loadline is a web app that reviews your training week with an avatar. It imports the workouts you record on an Apple Watch and shows fitness, fatigue and VO2max on one dashboard. Once a week, a 3D avatar speaks a short review of the week and offers two or three options for the next week.

- App (beta): https://api-qbvpsx77dq-an.a.run.app
- Click "Try as a guest" on the sign-in screen to see a dashboard and a weekly review with demo data. No sign-up is needed.
- Article: [How much should an LLM decide?](https://dev.to/iotarduino/how-much-should-an-llm-decide-building-an-avatar-that-reviews-your-training-week-with-fastapi-40fg) explains the design of the weekly review

## How the weekly review is made

- Code judges the week from the records: whether the user is tired, and how the week's training load compares with the user's own past nine weeks
- Gemini writes the avatar's line and the options, using the judgments as input
- Jev, a judge model, returns the probability that the line pushes the user too hard, gives medical advice, or recommends more training
- Code reads the probabilities and decides whether the avatar can use the line. If Gemini or Jev fails, or a probability is 0.35 or higher, the app uses prepared fallback lines, so a weekly review is always created

## Tech stack

- Frontend: React 19, TypeScript, Vite, Apache ECharts, three.js and three-vrm (`web/`)
- Backend: FastAPI on Python 3.12 (`api/`)
- DB: PostgreSQL on Neon
- Auth: Firebase Authentication
- Lines: Gemini on Vertex AI
- Line checks: Jev by TypeSafe AI
- Voice: Kokoro for English (`tts/`), Google Cloud Text-to-Speech for Japanese
- Hosting: Cloud Run, Cloud Storage, Cloud Scheduler and Cloud Tasks
- Workout import: Health Auto Export (iOS app)

## Backend layout

| Folder | Role |
|---|---|
| `api/app/routers/` | Receives requests and calls services |
| `api/app/services/` | Reads and writes the DB and calls domain and adapters in order |
| `api/app/domain/` | Calculations and judgments, with no DB or external services |
| `api/app/adapters/` | Calls Gemini, Jev, the voice services and Cloud Storage |

## Development

The detailed setup is in the Japanese README (section 13). The main commands run from the repository root:

- `docker compose up -d`: start PostgreSQL
- `make dev`: start the API on port 8000 and the frontend on port 5173
- `make check`: lint, type check and test the API, the frontend, `tts/` and the E2E code
- `make e2e`: run the Playwright end-to-end tests

## License

AGPL-3.0, except for the avatar model.

The avatar model (`web/public/models/sample.vrm`) is VRM1_Constraint_Twist_Sample, a sample model published by pixiv Inc. in [pixiv/three-vrm](https://github.com/pixiv/three-vrm). It is covered by the [VRM Public License 1.0](https://vrm.dev/licenses/1.0/), not by the AGPL.
