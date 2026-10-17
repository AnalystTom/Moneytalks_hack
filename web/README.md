# Council web

React + Vite + TypeScript. The boardroom follows the selected stone-grey / charcoal cartoon mockup: Warren at the head, Leopold left, Burry and Cramer right, a curved table and the chat panel on the right. Palette and typography are CSS variables in `src/style.css`. The flat scene uses HTML and CSS so speech stays readable without WebGL.

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

Upload CSV/JSON holdings (`ticker`, `shares`, `cost_basis` per share), optionally request the Plaid sandbox, and upload or write a persona profile. Holdings JSON can be an array or an object with a `holdings` array; broker JSON with a `positions` array is also accepted and normalized before submission. Ask a question and convene the council. The UI consumes POST SSE, reveals each verdict, stages a drum roll, shows Warren's ruling, and supports named-member follow-ups and roast mode. A failed or cancelled follow-up preserves the completed council session so you can ask again. Select a seat or a member in the strip for expanded verdicts. All four speech bubbles stay in the page layout and grow with their returned text; they are never line-clamped. BUY and SELL use thumbs-up/down icons, HOLD uses a pause icon, and pending members show an hourglass. The chair’s returned summary appears in Warren’s bubble. The page can scroll vertically for long answers. Narrow screens use two columns, with Warren first. No WebGL is required for the scene or transcript.

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

Four separate transparent cutouts in `public/portraits/` replace the old portrait atlas. Each was generated with Codex’s built-in image generation tool and visually inspected for a consistent cut-paper cartoon style. Files: `buffett.png`, `leopold.png`, `burry.png`, `cramer.png`.

Shared prompt: “Use case: illustration-story. Individual transparent waist-up character cutout for Council parody app. Flat South Park-style cut-paper cartoon, bold black outlines, simple round head, small black dot pupils, same coherent set design, no gradients or 3D. Front view seated pose, both shoulders and waist entirely visible, neutral hands at lower edge. Transparent background. Muted charcoal clothing, warm light skin. No text, logos, props, scenery, table, chair or other characters.”

Individual subjects:

- Warren Buffett: elderly white swept hair, round black glasses, charcoal suit, white shirt, dusty mauve tie, calm expression.
- Leopold Aschenbrenner: voluminous wavy brown hair, round black glasses, black suit, white shirt, black tie, curious expression.
- Michael Burry: side-swept black hair, no glasses, charcoal jacket, muted light-blue shirt, serious expression.
- Jim Cramer: bald with dark temple hair, dark goatee, white rolled-sleeve shirt, dusty mauve tie, expressive eyebrows.

## Review environment

Run browser testing on `big-machine-1` with an isolated profile. Never launch local review windows. Capture screenshots and a short working-flow video from the built UI before publishing a UI PR, then close only the processes created for that run. Remote verification results are recorded with the task evidence outside this worktree.

For this restyle, big-machine-1 was reported unreachable by the dispatch brief. No local browser or app was launched. Automated checks do not prove visual layout; built-app screenshots, video and fresh-user Playwright verification remain unavailable and must be stated in the PR.
