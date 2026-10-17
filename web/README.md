# Council web

React + Vite + TypeScript. See the [screen design](../data/spec.md#screen) for the boardroom layout and visual direction. Palette and typography are CSS variables in `src/style.css`.

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

The app loads `data/portfolio.json` and `data/PERSONA.md` automatically through Vite development endpoints or emitted build assets, normalizes broker positions, and ingests them with the existing API. A small portfolio chip appears only after the server accepts the context. The paperclip replaces CSV/JSON holdings while retaining the profile, then clears the previous conversation only after the replacement is accepted. Context failures show an explicit error and retry action.

Send a message to run the council. Returned verdicts and Warren's ruling appear as avatar messages. Reply to a returned member message for a named-member follow-up; clear the recipient to ask the full council again. Failed or cancelled messages stay in the composer for retry. Roast mode is available in the header.

Five cartoon members sit around the curved table. The current server supports four; Ray's seat stays empty until a real verdict arrives. No Ray opinion, confidence or source is supplied by the frontend. Stream events select idle, research, reveal, speaking and drum-roll poses. CSS transforms provide cutout motion and respect `prefers-reduced-motion`.

Bubbles use the server's `speech_bubble` field when returned, otherwise a clean first-sentence preview capped at fifteen words and 100 characters. Select a bubble, portrait or nameplate to view the full answer, reasons and valid sources. Warren's final details include his overall signal, summary, consensus and dissent. Chat history retains earlier returned answers.

Voice is loaded only when `/api/health` explicitly reports `voice: true` and sound is enabled. Actual playback starts and stops the speaking pose; text-only runs use a short speaking beat. Playback failures disable further audio loads for that run. A clip with no playback progress for 30 seconds releases the stream. Pausing or cancelling releases playback.

The checked-in context is demo data, not a connected bank account. The frontend never supplies financial verdicts, confidence, citations or balances itself and cannot certify the backend's research. Example-domain source URLs are excluded. Briefs and sessions remain in backend memory; refreshing reloads context.

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

Five separate transparent cutouts in `public/portraits/` replace the old portrait atlas. Each was generated with Codex’s built-in image generation tool and visually inspected for a consistent cut-paper cartoon style. Files: `buffett.png`, `leopold.png`, `burry.png`, `cramer.png`, `dalio.png`.

Shared prompt: “Use case: illustration-story. Individual transparent waist-up character cutout for Council parody app. Flat South Park-style cut-paper cartoon, bold black outlines, simple round head, small black dot pupils, same coherent set design, no gradients or 3D. Front view seated pose, both shoulders and waist entirely visible, neutral hands at lower edge. Transparent background. Muted charcoal clothing, warm light skin. No text, logos, props, scenery, table, chair or other characters.”

Individual subjects:

- Warren Buffett: elderly white swept hair, round black glasses, charcoal suit, white shirt, dusty mauve tie, calm expression.
- Leopold Aschenbrenner: regenerated against the supplied identity photograph; slim young man, light-brown swept-back side-parted hair, blue-grey eyes, no glasses, black ribbed mock-neck sweater.
- Michael Burry: side-swept black hair, no glasses, charcoal jacket, muted light-blue shirt, serious expression.
- Ray Dalio: receding swept-back grey hair, long face, no glasses, charcoal blazer and light-blue open-collar shirt.
- Jim Cramer: bald with dark temple hair, dark goatee, white rolled-sleeve shirt, dusty mauve tie, expressive eyebrows.

## Review environment

Run browser testing on `big-machine-1` with an isolated profile. Never launch local review windows. Capture screenshots and a short working-flow video from the built UI before publishing a UI PR, then close only the processes created for that run. Remote verification results are recorded with the task evidence outside this worktree.
