import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { executeBatch } from '../scripts/lib/batch.mjs';
import { executeRequest, publicError } from '../scripts/lib/core.mjs';
import { resolve } from 'node:path';

const folder = () => mkdtempSync(join(tmpdir(), 'jev-batch-test-'));
const request = id => ({ action: 'evaluate', request_id: id, use_case: 'batch test',
  request_schema_version: '1', question_set_version: '1', state_schema_version: '1',
  state: { word: id }, questions: { yes: { type: 'boolean', instructions: 'Is this valid?' } } });
const result = probability => ({ answers: { yes: { type: 'boolean', probability } } });
const deps = evaluateFn => ({ evaluateFn, credentialLoader: async () => 'fixture', sdkVersion: 'test' });
const batch = (...ids) => ({ action: 'batch', requests: ids.map(request) });
const lines = path => readFileSync(path, 'utf8').trim().split('\n').map(JSON.parse);

test('caps active provider calls and writes one progress line per request', async () => {
  const progressPath = join(folder(), 'progress.jsonl');
  let active = 0;
  let peak = 0;
  const releases = [];
  const running = executeBatch(batch('a', 'b', 'c', 'd'), deps(async () => {
    active++;
    peak = Math.max(peak, active);
    await new Promise(resolve => releases.push(resolve));
    active--;
    return result(0.5);
  }), { progressPath, concurrency: 2 });
  while (releases.length < 2) await new Promise(resolve => setImmediate(resolve));
  assert.equal(peak, 2);
  releases.splice(0).forEach(release => release());
  while (releases.length < 2) await new Promise(resolve => setImmediate(resolve));
  releases.splice(0).forEach(release => release());
  const output = await running;
  assert.equal(peak, 2);
  assert.deepEqual(output.summary, { ok: 4, failed: 0, skipped: 0, retried: 0,
    rate_limited: 0, wall_time_ms: output.summary.wall_time_ms });
  assert.deepEqual(lines(progressPath).map(line => line.request_id).sort(), ['a', 'b', 'c', 'd']);
});

test('honors Retry-After and retries provider failure with the same request ID', async () => {
  const progressPath = join(folder(), 'progress.jsonl');
  const waits = [];
  let calls = 0;
  const output = await executeBatch(batch('stable'), deps(async () => {
    calls++;
    if (calls === 1) {
      const error = new Error('private provider text');
      error.statusCode = 429;
      error.responseHeaders = { 'retry-after': '12' };
      throw error;
    }
    if (calls === 2) throw new Error('private failure');
    return result(0.8);
  }), { progressPath, sleep: async ms => waits.push(ms), random: () => 0 });
  assert.deepEqual(waits, [12_000, 2_000]);
  assert.equal(calls, 3);
  assert.deepEqual(output.summary, { ok: 1, failed: 0, skipped: 0, retried: 2,
    rate_limited: 1, wall_time_ms: output.summary.wall_time_ms });
  assert.equal(lines(progressPath)[0].request_id, 'stable');
  assert.equal(lines(progressPath)[0].attempts, 3);
  assert.equal(readFileSync(progressPath, 'utf8').includes('private'), false);
});

test('resume skips succeeded IDs and retries failed IDs', async () => {
  const progressPath = join(folder(), 'progress.jsonl');
  writeFileSync(progressPath, JSON.stringify({ request_id: 'done', ok: true }) + '\n' +
    JSON.stringify({ request_id: 'again', ok: false }) + '\n');
  let calls = 0;
  const output = await executeBatch(batch('done', 'again'), deps(async () => { calls++; return result(0.5); }),
    { progressPath, resume: true });
  assert.equal(calls, 1);
  assert.deepEqual(output.summary, { ok: 1, failed: 0, skipped: 1, retried: 0,
    rate_limited: 0, wall_time_ms: output.summary.wall_time_ms });
  assert.equal(lines(progressPath).length, 3);
});

test('summary counts terminal failures and does not retry invalid requests', async () => {
  const progressPath = join(folder(), 'progress.jsonl');
  const requests = [request('good'), request('bad')];
  requests[1].questions = {};
  const output = await executeBatch({ action: 'batch', requests }, deps(async () => result(0.5)),
    { progressPath });
  assert.equal(output.ok, false);
  assert.equal(output.summary.ok, 1);
  assert.equal(output.summary.failed, 1);
  assert.equal(output.summary.retried, 0);
  assert.equal(lines(progressPath).find(line => line.request_id === 'bad').error.code, 'invalid_input');
});

test('clamps tiny probability overrun and names the failing check', async () => {
  const good = await executeRequest(request('rounding'), deps(async () => result(1 + 1e-7)));
  assert.equal(good.answers.yes.probability, 1);
  let error;
  try { await executeRequest(request('bad'), deps(async () => result(1.01))); }
  catch (caught) { error = publicError(caught); }
  assert.equal(error.error.code, 'provider_failed');
  assert.equal(error.error.check, 'boolean_probability');
});

test('reclaims a failed stored run with the same request ID during batch retry', async () => {
  const root = folder();
  const database = join(root, 'runs.sqlite');
  const progressPath = join(root, 'progress.jsonl');
  writeFileSync(database, '');
  await executeRequest({ action: 'migrate', database }, {
    schemaPath: resolve(import.meta.dirname, '..', 'references', 'agent-os-migration.sql'),
  });
  let calls = 0;
  const stored = request('same-id');
  stored.storage = { database, required: true };
  const output = await executeBatch({ action: 'batch', requests: [stored] }, deps(async () => {
    calls++;
    if (calls === 1) throw new Error('provider failure');
    return result(0.5);
  }), { progressPath, sleep: async () => {}, random: () => 0 });
  assert.equal(calls, 2);
  assert.equal(output.summary.retried, 1);
  assert.equal(lines(progressPath)[0].result.recording.status, 'stored');
});
