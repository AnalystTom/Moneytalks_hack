import assert from 'node:assert/strict';
import test from 'node:test';
import { checkConfig, run, verify } from '../src/index.js';

// Isolated transport fixtures; tests never call providers or create application data.
const env = {
  NICRRON_API_KEY: 'test-nicrron-key',
  PRISMTRACE_API_KEY: 'test-prism-key',
  PRISMTRACE_PROJECT_ID: '12345678-1234-1234-1234-123456789abc',
};
const completion = { model: 'test-model', choices: [{ message: { content: 'test response' } }] };

test('missing configuration and invalid project IDs fail before any provider call', async () => {
  assert.throws(() => checkConfig({}), /Missing configuration/);
  assert.throws(() => checkConfig({ ...env, PRISMTRACE_PROJECT_ID: 'invalid' }), /project UUID/);
  await assert.rejects(run('prompt', {}, () => assert.fail('must not call providers')), /Missing configuration/);
  await assert.rejects(run(' ', env, () => assert.fail('must not call providers')), /nonempty prompt/);
});

test('forwards the real completion and usage to PRISM with isolated credentials', async () => {
  const calls: { url: string; body: Record<string, unknown>; headers: Headers; redirect: RequestRedirect | undefined }[] = [];
  const result = await run('test input', env, async (url, options) => {
    calls.push({ url, body: JSON.parse(String(options.body)), headers: new Headers(options.headers), redirect: options.redirect });
    return Response.json(calls.length === 1 ? { ...completion, usage: { prompt_tokens: 9, completion_tokens: 2 } } : { id: 'stored-trace-id' });
  });
  assert.equal(calls[0].url, 'https://api.nicrron.ai/v1/chat/completions');
  assert.equal(calls[0].body.model, 'nicrron/auto');
  assert.equal(calls[0].headers.get('Authorization'), `Bearer ${env.NICRRON_API_KEY}`);
  assert.equal(calls[1].url, 'https://prism.blockconvey.com/api/traces');
  assert.equal(calls[1].headers.get('X-PRISMtrace-Key'), env.PRISMTRACE_API_KEY);
  assert.equal(calls[1].headers.get('Authorization'), null);
  assert.deepEqual(calls[1].body.input_messages, calls[0].body.messages);
  assert.equal(calls[1].body.output_message, completion.choices[0].message.content);
  assert.equal(calls[1].body.model, completion.model);
  assert.equal(calls[1].body.token_count_input, 9);
  assert.equal(calls[1].body.token_count_output, 2);
  assert.match(String(calls[1].body.session_id), /^[0-9a-f-]{36}$/);
  assert.equal(calls[1].redirect, 'error');
  assert.equal(result.traceId, 'stored-trace-id');
});

test('a rejected model request is not submitted as a successful trace', async () => {
  let calls = 0;
  await assert.rejects(run('prompt', env, async () => {
    calls++;
    return new Response('private provider error', { status: 401 });
  }), /^Error: Nicrron returned HTTP 401\.$/);
  assert.equal(calls, 1);
});

test('missing output is not fabricated or submitted to PRISM', async () => {
  for (const body of [null, [], { choices: [] }, { choices: [null] }, { choices: [{ message: null }] }]) {
    await assert.rejects(run('prompt', env, async () => Response.json(body)), /invalid JSON object|no text completion/);
  }
});

test('trace failure preserves the model result without claiming delivery', async () => {
  let calls = 0;
  const result = await run('prompt', env, async () => ++calls === 1 ? Response.json(completion) : new Response('', { status: 503 }));
  assert.equal(result.output, 'test response');
  assert.equal(result.traceId, null);
  assert.match(result.error, /PRISM returned HTTP 503/);
});

test('a missing trace receipt does not claim delivery', async () => {
  let calls = 0;
  const result = await run('prompt', env, async () => Response.json(++calls === 1 ? completion : {}));
  assert.equal(result.traceId, null);
  assert.match(result.error, /no trace ID/);
});

test('verification reflects provider state without inventing a connected result', async () => {
  assert.deepEqual(await verify(env, async () => Response.json({ live_connected: true, blocked_step: null })), { liveConnected: true, blockedStep: null });
  assert.deepEqual(await verify(env, async () => Response.json({ live_connected: false, blocked_step: 'live_event_received' })), { liveConnected: false, blockedStep: 'live_event_received' });
  assert.equal((await verify(env, async () => Response.json({}))).liveConnected, false);
});

test('network and malformed responses fail without printing provider secrets', async () => {
  await assert.rejects(run('prompt', env, async () => { throw new Error('secret'); }), /^Error: Nicrron could not be reached or timed out\.$/);
  await assert.rejects(run('prompt', env, async () => new Response('not JSON')), /invalid JSON object/);
});
