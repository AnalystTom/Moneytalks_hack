# Council web

React + Vite + TypeScript + react-three-fiber. The mahogany / pine / brass direction follows mockup A. Palette and typography are CSS variables in `src/style.css`.

## Run

Use Node 22 and Python 3.12. From the repository root:

```sh
cd server
uv sync --python 3.12
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second shell:

```sh
cd web
npm ci
npm run dev
```

Open the Vite URL (normally `http://127.0.0.1:5173`). `/api` proxies to FastAPI on port 8000. No backend change is needed. `npm run build` emits `web/dist`; see [Cloudflare deployment](../server/README.md#deploy-cloudflare) for production hosting. `npm run preview` serves the build and inherits the same API proxy; keep FastAPI running.

## Journey

Upload CSV/JSON holdings (`ticker`, `shares`, `cost_basis` per share), optionally request the Plaid sandbox, and upload or write a persona profile. Holdings JSON can be an array or an object with a `holdings` array; broker JSON with a `positions` array is also accepted and normalized before submission. Ask a question and convene the council. The UI consumes POST SSE, reveals each verdict, stages a drum roll, shows Warren's ruling, and supports named-member follow-ups and roast mode. A failed or cancelled follow-up preserves the completed council session so you can ask again. Select a seat or a member in the strip for expanded verdicts. The transcript works even when WebGL is unavailable.

Voice plays sequentially when `/api/voice/speak` is configured. Each clip can finish naturally; 30 seconds without playback progress reports a timeout and advances the stream. Playback errors are explicit. Pausing a clip or disabling sound releases the stream to continue; cancelling the session stops playback and the request.

**Load demo** reads `data/portfolio.json` through a Vite development endpoint or emitted build asset. As with uploaded broker JSON, position `symbol`, `qty` and `avg_entry_price` become `ticker`, `shares` and `cost_basis`; snapshot market prices and account balances are not submitted. The profile is loaded verbatim from `data/PERSONA.md`; the question follows the journey in `data/spec.md`. This is explicitly labelled synthetic demo data. Sandbox is a request to the server, never a claim that a real bank is connected.

The existing server returns canned verdicts without a model key, stub market/bank data and placeholder research links. The preview notice stays visible and example-domain source URLs are shown as unavailable. The frontend never supplies financial verdicts, confidence, citations or balances itself. It cannot certify the backend's research as live. There is no client-side answer cache; retrying after a backend restart requires a new brief.

## Checks

```sh
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

GitHub Actions runs these checks plus the existing backend tests. The backend currently has no formatting, lint or typecheck scripts; adding them is separate work.

## Portrait asset

`public/council-portraits.png` was generated with Codex's built-in image generation tool. One square atlas: Warren / Leopold on the top row, Cramer / Burry on the bottom row. The scene samples each tile independently. Prompt: “Four equal portrait tiles, recognisable stylised comical clay caricatures, seated waist-up in a mahogany boardroom, warm amber light, pine green background. Buffett: white hair, glasses and red tie; Leopold: wavy hair, round glasses and black sweater; Cramer: bald, goatee, rolled sleeves and expressive hands; Burry: dark hair, dark suit, thoughtful expression. No text, financial figures, charts, logos or watermark.”

## Review environment

Run browser testing on `big-machine-1` with an isolated profile. Never launch local review windows. Capture screenshots and a short working-flow video from the built UI before publishing a UI PR, then close only the processes created for that run. Remote verification results are recorded with the task evidence outside this worktree.
