import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { executeRequest, JevError, publicError } from '../scripts/lib/core.mjs';

const schemaPath = resolve(import.meta.dirname, '..', 'references', 'agent-os-migration.sql');

function input(overrides = {}) {
  return {
    action: 'evaluate',
    request_id: 'run-1',
    use_case: 'offline behavior test',
    request_schema_version: '1',
    question_set_version: 'test-v1',
    state_schema_version: 'state-v1',
    state: { text: 'Safe fixture state' },
    questions: {
      route: {
        type: 'choice',
        instructions: 'Choose a route.',
        criteria: { alpha: 'First route', beta: 'Second route' },
      },
      score: {
        type: 'score',
        instructions: 'Score the fit.',
        criteria: ['Low', 'Medium', 'High'],
      },
      verified: {
        type: 'boolean',
        instructions: 'Is the condition verified?',
      },
    },
    ...overrides,
  };
}

function providerResult(overrides = {}) {
  return {
    answers: {
      route: { type: 'choice', choice: 'alpha', probabilities: { alpha: 0.8, beta: 0.2 }, confidence: 0.9 },
      score: { type: 'score', score: 1.5, probabilities: { '0': 0.1, '1': 0.3, '2': 0.6 }, confidence: 0.8 },
      verified: { type: 'boolean', probability: 0.75 },
    },
    usage: { input_tokens: 100, output_tokens: 20, cost: 0.0002 },
    warnings: [],
    model: 'typesafe/jev-test',
    ...overrides,
  };
}

function dependencies(evaluateFn = async () => providerResult()) {
  return {
    evaluateFn,
    credentialLoader: async () => 'test-key',
    sdkVersion: '7.0.107',
    schemaPath,
  };
}

async function isolatedDatabase() {
  const folder = mkdtempSync(join(tmpdir(), 'jev-test-'));
  const database = join(folder, 'agent-os.sqlite');
  writeFileSync(database, '');
  await executeRequest({ action: 'migrate', database }, { schemaPath });
  return database;
}

test('parses Choice, Score, and boolean answers', async () => {
  const database = await isolatedDatabase();
  const result = await executeRequest(input({ storage: { database, required: true } }), dependencies());
  assert.equal(result.ok, true);
  assert.equal(result.answers.route.choice, 'alpha');
  assert.equal(result.answers.score.score, 1.5);
  assert.equal(result.answers.verified.probability, 0.75);
  assert.equal(result.answers.route.confidence, 0.9);
  assert.equal(result.answers.score.confidence, 0.8);
  assert.deepEqual(result.usage, { input_tokens: 100, output_tokens: 20, total_tokens: 120 });
  assert.equal(result.provider_cost.amount, 0.0002);
  assert.equal(result.quality.status, 'unchecked');
  const check = new DatabaseSync(database);
  const stored = check.prepare('SELECT input_tokens, output_tokens, total_tokens, provider_cost_amount FROM jev_runs WHERE request_id = ?').get('run-1');
  check.close();
  assert.deepEqual({ ...stored }, {
    input_tokens: 100, output_tokens: 20, total_tokens: 120, provider_cost_amount: 0.0002,
  });
});

test('rejects invalid input before calling the provider', async () => {
  let calls = 0;
  const bad = input({ questions: { score: { type: 'score', instructions: 'Score.', criteria: ['only'] } } });
  await assert.rejects(
    executeRequest(bad, dependencies(async () => { calls += 1; return providerResult(); })),
    error => error instanceof JevError && error.code === 'invalid_input',
  );
  assert.equal(calls, 0);
});

test('reports a missing key without a provider call', async () => {
  let calls = 0;
  const deps = dependencies(async () => { calls += 1; return providerResult(); });
  deps.credentialLoader = async () => '';
  await assert.rejects(
    executeRequest(input(), deps),
    error => error instanceof JevError && error.code === 'missing_credential',
  );
  assert.equal(calls, 0);
});

test('sanitizes provider errors', async () => {
  const planted = 'SECRET-MUST-NOT-LEAK';
  const rawState = 'RAW-STATE-MUST-NOT-LEAK';
  const failing = input({ state: { text: rawState } });
  let caught;
  try {
    await executeRequest(failing, dependencies(async () => {
      const error = new Error(`${planted} ${rawState}`);
      error.statusCode = 429;
      throw error;
    }));
  } catch (error) {
    caught = publicError(error);
  }
  const serialized = JSON.stringify(caught);
  assert.equal(caught.error.code, 'provider_rate_limited');
  assert.equal(serialized.includes(planted), false);
  assert.equal(serialized.includes(rawState), false);
});

test('keeps returned model, version, and cost unknown when absent', async () => {
  const result = await executeRequest(
    input(),
    dependencies(async () => providerResult({ model: undefined, usage: {} })),
  );
  assert.equal(result.model.returned, null);
  assert.equal(result.model.version, null);
  assert.deepEqual(result.provider_cost, {
    status: 'unknown', amount: null, currency: null, source: null,
  });
  assert.equal(result.usage.total_tokens, null);
});

test('records an actual zero provider charge when supplied', async () => {
  const result = await executeRequest(
    input(),
    dependencies(async () => providerResult({
      usage: { cost: '0' }, id: 'gen_test-1',
    })),
  );
  assert.deepEqual(result.provider_cost, {
    status: 'known', amount: 0, currency: 'USD', source: 'usage.cost',
  });
  assert.equal(result.provider.generation_id, 'gen_test-1');
});

test('drops arbitrary provider warning text from the result', async () => {
  const planted = 'WARNING-SECRET-MUST-NOT-LEAK';
  const result = await executeRequest(
    input(),
    dependencies(async () => providerResult({ warnings: [{ type: 'other', message: planted }] })),
  );
  assert.deepEqual(result.warnings, [{ type: 'other' }]);
  assert.equal(JSON.stringify(result).includes(planted), false);
});

test('classifies a bounded provider timeout', async () => {
  let sawSignal = false;
  await assert.rejects(
    executeRequest(input(), dependencies(async request => {
      sawSignal = request.abortSignal instanceof AbortSignal;
      throw new DOMException('private timeout detail', 'TimeoutError');
    })),
    error => error instanceof JevError && error.code === 'provider_timeout',
  );
  assert.equal(sawSignal, true);
});

test('rolls back the complete migration when any statement fails', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'jev-migration-test-'));
  const database = join(folder, 'agent-os.sqlite');
  const brokenSchema = join(folder, 'broken.sql');
  writeFileSync(database, '');
  writeFileSync(brokenSchema, 'BEGIN IMMEDIATE; CREATE TABLE partial(value TEXT); INVALID SQL; COMMIT;');
  await assert.rejects(
    executeRequest({ action: 'migrate', database }, { schemaPath: brokenSchema }),
    error => error instanceof JevError && error.code === 'migration_failed',
  );
  const check = new DatabaseSync(database);
  const row = check.prepare("SELECT name FROM sqlite_master WHERE name = 'partial'").get();
  check.close();
  assert.equal(row, undefined);
});

test('returns a completed result when optional logging fails', async () => {
  const result = await executeRequest(
    input({ storage: { database: '/path/that/does/not/exist.sqlite', required: false } }),
    dependencies(),
  );
  assert.equal(result.ok, true);
  assert.equal(result.recording.status, 'failed');
  assert.equal(result.recording.error.code, 'storage_failed');
});

test('names the migrate fix when the store has no Jev tables', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'jev-empty-store-test-'));
  const database = join(folder, 'caller-store.sqlite');
  writeFileSync(database, '');
  let calls = 0;
  const deps = dependencies(async () => { calls += 1; return providerResult(); });
  const request = input({ storage: { database, required: true } });
  await assert.rejects(
    executeRequest(request, deps),
    error => error instanceof JevError && error.code === 'storage_not_migrated' &&
      error.message === 'This store has no Jev tables. Run the migrate action on it first.',
  );
  assert.equal(calls, 0);
  const check = new DatabaseSync(database);
  const tables = check.prepare("SELECT name FROM sqlite_master WHERE type = 'table'").all();
  check.close();
  assert.deepEqual(tables, []);
  await executeRequest({ action: 'migrate', database }, { schemaPath });
  const result = await executeRequest(request, deps);
  assert.equal(result.recording.status, 'stored');
  assert.equal(calls, 1);
});

test('keeps storage_failed when a missing table is outside the Jev schema', async () => {
  const database = await isolatedDatabase();
  const setup = new DatabaseSync(database);
  setup.exec(`CREATE TRIGGER audit_jev_runs AFTER INSERT ON jev_runs
    BEGIN INSERT INTO audit_events(request_id) VALUES (NEW.request_id); END;`);
  setup.close();
  let calls = 0;
  await assert.rejects(
    executeRequest(
      input({ storage: { database, required: true } }),
      dependencies(async () => { calls += 1; return providerResult(); }),
    ),
    error => error instanceof JevError && error.code === 'storage_failed',
  );
  assert.equal(calls, 0);
});

test('keeps a completed answer when final storage fails and prevents unsafe replay', async () => {
  let calls = 0;
  const database = await isolatedDatabase();
  const storage = await import('../scripts/lib/storage.mjs');
  const deps = dependencies(async () => { calls += 1; return providerResult(); });
  deps.storage = { ...storage, finishRun() { throw new Error('private storage detail'); } };
  const request = input({ storage: { database, required: true } });
  const result = await executeRequest(request, deps);
  assert.equal(result.ok, true);
  assert.equal(result.answers.route.choice, 'alpha');
  assert.equal(result.recording.status, 'failed');
  assert.equal(JSON.stringify(result).includes('private storage detail'), false);
  await assert.rejects(
    executeRequest(request, deps),
    error => error instanceof JevError && error.code === 'request_in_progress',
  );
  assert.equal(calls, 1);
});

test('marks quality reviewed only after feedback with evidence', async () => {
  const database = await isolatedDatabase();
  const runInput = input({ storage: { database, required: true } });
  await executeRequest(runInput, dependencies());
  await assert.rejects(
    executeRequest({
      action: 'feedback', database, request_id: 'run-1', kind: 'review',
      assessment: 'accepted', evidence_ref: '',
    }, { schemaPath }),
    error => error instanceof JevError && error.code === 'invalid_input',
  );
  const feedback = await executeRequest({
    action: 'feedback', database, request_id: 'run-1', kind: 'review',
    assessment: 'accepted', fit: 'fit', rationale: 'The bounded route was useful.',
    evidence_ref: '/tmp/review-evidence.json',
  }, { schemaPath });
  assert.equal(feedback.quality.status, 'reviewed');
  assert.equal(feedback.quality.evidence_count, 1);
});

test('prevents concurrent duplicates and replays the completed result', async () => {
  const database = await isolatedDatabase();
  let release;
  const gate = new Promise(resolveGate => { release = resolveGate; });
  let calls = 0;
  const deps = dependencies(async () => {
    calls += 1;
    await gate;
    return providerResult();
  });
  const request = input({ storage: { database, required: true } });
  const first = executeRequest(request, deps);
  await assert.rejects(
    executeRequest(request, dependencies()),
    error => error instanceof JevError && error.code === 'request_in_progress',
  );
  release();
  const completed = await first;
  assert.equal(completed.recording.status, 'stored');
  const replay = await executeRequest(request, dependencies(async () => {
    calls += 1;
    return providerResult();
  }));
  assert.equal(replay.recording.idempotent_replay, true);
  assert.equal(calls, 1);
});
