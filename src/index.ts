import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const prismHost = 'https://prism.blockconvey.com';
type Env = Record<string, string | undefined>;
type Config = Env & {
  NICRRON_API_KEY: string;
  PRISMTRACE_API_KEY: string;
  PRISMTRACE_PROJECT_ID: string;
};
type Fetcher = (url: string, options: RequestInit) => Promise<Response>;
const required = ['NICRRON_API_KEY', 'PRISMTRACE_API_KEY', 'PRISMTRACE_PROJECT_ID'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function checkConfig(env: Env): asserts env is Config {
  const missing = required.filter((name) => !env[name]?.trim());
  if (missing.length) throw new Error(`Missing configuration: ${missing.join(', ')}`);
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(env.PRISMTRACE_PROJECT_ID ?? '')) {
    throw new Error('PRISMTRACE_PROJECT_ID must be the project UUID from PRISM Settings.');
  }
}

async function request(fetcher: Fetcher, url: string, options: RequestInit, service: string): Promise<Record<string, unknown>> {
  let response;
  try {
    response = await fetcher(url, { ...options, redirect: 'error', signal: AbortSignal.timeout(60_000) });
  } catch {
    throw new Error(`${service} could not be reached or timed out.`);
  }
  if (!response.ok) throw new Error(`${service} returned HTTP ${response.status}.`);
  try {
    const data: unknown = await response.json();
    if (!isRecord(data)) throw new Error();
    return data;
  } catch {
    throw new Error(`${service} returned an invalid JSON object.`);
  }
}

export async function run(prompt: string, env: Env = process.env, fetcher: Fetcher = fetch) {
  checkConfig(env);
  if (!prompt?.trim()) throw new Error('Supply a nonempty prompt: npm run smoke -- "your prompt"');
  const inputMessages = [{ role: 'user', content: prompt }];
  const started = performance.now();
  const completion = await request(fetcher, 'https://api.nicrron.ai/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${env.NICRRON_API_KEY}` },
    body: JSON.stringify({ model: env.NICRRON_MODEL?.trim() || 'nicrron/auto', messages: inputMessages }),
  }, 'Nicrron');
  const latencyMs = Math.round(performance.now() - started);
  const choice: unknown = Array.isArray(completion.choices) ? completion.choices[0] : undefined;
  const message = isRecord(choice) && isRecord(choice.message) ? choice.message : undefined;
  const output = message?.content;
  if (typeof output !== 'string' || !output.trim() || typeof completion.model !== 'string' || !completion.model.trim()) {
    throw new Error('Nicrron returned no text completion or model; no trace was submitted.');
  }
  const trace: Record<string, unknown> = {
    project_id: env.PRISMTRACE_PROJECT_ID,
    model: completion.model,
    input_messages: inputMessages,
    output_message: output,
    latency_ms: latencyMs,
    session_id: randomUUID(),
    agent_id: 'moneytalks-setup',
  };
  const usage = isRecord(completion.usage) ? completion.usage : {};
  if (typeof usage.prompt_tokens === 'number' && Number.isInteger(usage.prompt_tokens) && usage.prompt_tokens >= 0) trace.token_count_input = usage.prompt_tokens;
  if (typeof usage.completion_tokens === 'number' && Number.isInteger(usage.completion_tokens) && usage.completion_tokens >= 0) trace.token_count_output = usage.completion_tokens;
  let receipt;
  try {
    receipt = await request(fetcher, `${prismHost}/api/traces`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-PRISMtrace-Key': env.PRISMTRACE_API_KEY },
      body: JSON.stringify(trace),
    }, 'PRISM');
    if (typeof receipt.id !== 'string' || !receipt.id.trim()) throw new Error('PRISM returned no trace ID.');
  } catch (error) {
    // A setup probe must report failed delivery, while preserving the paid model result.
    return { output, model: completion.model, sessionId: trace.session_id, traceId: null, error: error instanceof Error ? error.message : 'PRISM trace delivery failed.' };
  }
  return { output, model: completion.model, sessionId: trace.session_id, traceId: receipt.id };
}

export async function verify(env: Env = process.env, fetcher: Fetcher = fetch) {
  checkConfig(env);
  const report = await request(fetcher, `${prismHost}/api/setup-doctor?project_id=${encodeURIComponent(env.PRISMTRACE_PROJECT_ID)}`, {
    headers: { 'X-PRISMtrace-Key': env.PRISMTRACE_API_KEY },
  }, 'PRISM');
  return { liveConnected: report.live_connected === true, blockedStep: typeof report.blocked_step === 'string' ? report.blocked_step : null };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const command = process.argv[2] ?? 'check';
    if (command === 'check') {
      checkConfig(process.env);
      console.log('Configuration present. Credentials and provider delivery have not been verified.');
    } else if (command === 'run') {
      const result = await run(process.argv.slice(3).join(' '));
      console.log(JSON.stringify(result, null, 2));
      if (result.error) process.exitCode = 1;
    } else if (command === 'verify') {
      const report = await verify();
      console.log(JSON.stringify(report, null, 2));
      if (!report.liveConnected) process.exitCode = 1;
    } else {
      throw new Error('Usage: npm start -- check | run "prompt" | verify');
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : 'Setup failed.');
    process.exitCode = 1;
  }
}
