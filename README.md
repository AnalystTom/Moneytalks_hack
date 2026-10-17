# Money Talks 2 setup

Basic TypeScript + Node.js template with Nicrron + PRISM integration for the [October 17 builder resource pack](https://docs.google.com/document/d/1rm5ev9mj_leu2w7OVlFVmKaCT-OvZZ9tSibbC4lzd08/edit). Requires Node.js 22+. No product or track has been selected.

## Develop

```sh
npm ci
npm run dev
npm run typecheck
npm test
npm run build
npm start
```

`src/index.ts` is the CLI entry point; `test/setup.test.ts` holds the tests. `dev` watches TypeScript source. `build` compiles the application to `dist/index.js`; `start` runs that compiled entry point. The default command checks configuration and makes no provider calls. Missing configuration produces an explicit error. Pass `run "your prompt"` or `verify` to `npm start --` to use the compiled integration commands.

TypeScript, tsx and Node types are development dependencies; there are no runtime packages. `package-lock.json` pins installation versions. `.env` and generated `dist/` output stay ignored.

## Activate your accounts

1. Create or sign into your account using the [Nicrron event redemption link](https://nicrron.ai/redeem?code=FINTECH-LPBMK). The pack lists $250 from `FINTECH-LPBMK` plus $10 at signup, expiring **October 18, 2026 at 6:00 PM ET**. Confirm the balance in your account; this repo cannot verify redemption.
2. Create a key at [Nicrron API keys](https://nicrron.ai/dashboard/keys).
3. Create **one team workspace** at [PRISM signup](https://prism.blockconvey.com/signup). Redeem `MONEYTALKS#2` in Settings → Billing. Copy the project UUID from Settings → Project and create an API key in Settings → API Keys.
4. On a new checkout, create `.env` only if it does not exist, then fill the three required values privately. Preserve existing credentials:

   ```sh
   test -e .env || cp .env.example .env
   chmod 600 .env
   ```

Do not commit keys or paste them into prompts. `.env` files are ignored. Keys stay in the process and are sent only to their respective provider. You can also supply these environment variables through your secret manager.

## Verify the connection

```sh
npm run setup:check
npm run smoke -- "Hello, MONEY TALKS!"
npm run prism:verify
npm test
npm run typecheck
npm run build
```

`setup:check` only checks configuration presence and project ID format. `smoke` makes **one billable model call** through Nicrron, then sends that actual input, reply, returned model, measured latency and available token counts to PRISM. Both providers receive the prompt and response; use only non-sensitive input. It prints the actual response and PRISM trace ID. A PRISM failure preserves the model response but exits unsuccessfully; rerunning the smoke command makes another model call.

`prism:verify` reads PRISM's setup doctor; an unsuccessful connection exits with an error status. Confirm the returned trace ID in the PRISM dashboard and inspect the recorded input and output. Connection health alone does not prove scoring, track requirements, or credit redemption.

This is a terminal setup probe, with a new session per invocation. It deliberately waits for PRISM's receipt. In a product, move trace delivery off the response path with a managed queue or supported SDK. This HTTP path records a single exchange; it does **not** create full tool trajectories or enforce guardrails. Failed model calls are reported locally and are not submitted as successful traces.

## Before judging

Build a real agent and collect **50+ actual runs before improving it**, as requested by the pack. Do not manufacture runs, failures, scores or financial data. Use public source material or non-sensitive inputs; never submit personal bank details or real card numbers.

Pick a track and capture all three required proofs:

| Track | PRISM proofs |
| --- | --- |
| Money Intelligence | Assigned knowledge base used in retrieval; root cause cluster of 3+ failed runs with your explanation; custom evaluator comparing v1/v2 on the same inputs. |
| Money Operations | A run with 6+ tool steps; a workflow alert firing on a real run; root cause cluster of 3+ failures and v2 passing the same inputs. |
| Trust & Risk | Custom finance guardrail in enforce mode blocking a real run; block check verdict with your assessment; root cause cluster of 3+ failed or blocked runs. |

For Operations, use PRISM's Python SDK or supported OpenTelemetry instrumentation for full trajectories. For Trust & Risk, choose an enforcement integration compatible with Nicrron and verify it before exposing outputs; this probe provides no enforcement. Knowledge bases, evaluators, alerts and account settings still require configuration for the chosen project.

The pack permits Nicrron API use to meet the NicrronNinoo requirement. Ninoo Builder/Code and ElevenLabs are optional. `ELEVENLABS_API_KEY` is included in the environment template for later use; no voice integration is implemented.

## References and checks

- [Nicrron quickstart](https://nicrron.ai/docs/quickstart)
- [PRISM integration/API documentation](https://blockconvey.com/docs)

The automated tests use isolated transport fixtures, make no provider calls and create no product data. Strict TypeScript checks cover application and test code. No formatter, linter or CI pipeline is configured in this starter. No browser UI, deployment or judging evidence is included.
