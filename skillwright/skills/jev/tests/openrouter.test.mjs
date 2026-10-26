import assert from 'node:assert/strict';
import test from 'node:test';
import { evaluateOpenRouter, OPENROUTER_URL } from '../scripts/lib/openrouter.mjs';
import { executeRequest, MODEL_ID, publicError } from '../scripts/lib/core.mjs';

const request = {
  action: 'evaluate', request_id: 'provider-shape', use_case: 'mock provider',
  request_schema_version: '1', question_set_version: '1', state_schema_version: '1',
  state: { word: 'watch' },
  questions: {
    yes: { type: 'boolean', instructions: 'Is this a watch?' },
    kind: { type: 'choice', instructions: 'Which kind?', criteria: { watch: 'Watch', other: 'Other' } },
    fit: { type: 'score', instructions: 'How good?', criteria: ['Low', 'High'] },
  },
};

test('posts OpenRouter shape and maps noul, choice, score, and confidence', async () => {
  let called = 0;
  const fetchFn = async (url, options) => {
    called++;
    assert.equal(url, OPENROUTER_URL);
    assert.equal(options.method, 'POST');
    assert.equal(options.headers.Authorization, 'Bearer fixture-key');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), {
      model: MODEL_ID,
      state: request.state,
      questions: {
        yes: { type: 'noul', instructions: 'Is this a watch?' },
        kind: request.questions.kind,
        fit: request.questions.fit,
      },
    });
    return { ok: true, json: async () => ({
      id: 'gen-test', model: 'typesafe/jev-1.13-20260917',
      usage: { input_tokens: 10, output_tokens: 3, cost: 0.000015 },
      answers: {
        yes: { type: 'noul', noul: 0.82, confidence: 0.7 },
        kind: { type: 'choice', choice: 'watch', probabilities: { watch: 0.9, other: 0.1 }, confidence: 0.8 },
        fit: { type: 'score', score: 1, probabilities: { '0': 0.2, '1': 0.8 }, confidence: 0.6 },
      },
    }) };
  };
  const result = await executeRequest(request, {
    credentialLoader: async () => 'fixture-key',
    evaluateFn: input => evaluateOpenRouter(input, fetchFn),
    sdkVersion: 'openrouter-direct-v1',
  });
  assert.equal(called, 1);
  assert.deepEqual(result.answers.yes, { type: 'boolean', probability: 0.82, confidence: 0.7 });
  assert.equal(result.answers.kind.confidence, 0.8);
  assert.equal(result.answers.fit.confidence, 0.6);
  assert.equal(result.model.returned, 'typesafe/jev-1.13-20260917');
  assert.equal(result.provider.generation_id, 'gen-test');
  assert.deepEqual(result.usage, { input_tokens: 10, output_tokens: 3, total_tokens: 13 });
  assert.equal(result.provider_cost.amount, 0.000015);
});

test('maps HTTP 429 Retry-After and hides provider details', async () => {
  const fetchFn = async () => ({ ok: false, status: 429, headers: new Headers({ 'Retry-After': '3' }) });
  let error;
  try {
    await executeRequest(request, {
      credentialLoader: async () => 'fixture-key',
      evaluateFn: input => evaluateOpenRouter(input, fetchFn),
      sdkVersion: 'openrouter-direct-v1',
    });
  } catch (caught) { error = publicError(caught); }
  assert.equal(error.error.code, 'provider_rate_limited');
  assert.equal(error.error.retry_after_ms, 3000);
  assert.equal(JSON.stringify(error).includes('fixture-key'), false);
});

test('maps auth and malformed answers to safe errors', async () => {
  for (const [fetchFn, code] of [
    [async () => ({ ok: false, status: 401, headers: new Headers() }), 'provider_authentication_failed'],
    [async () => ({ ok: true, json: async () => ({ answers: {} }) }), 'provider_failed'],
  ]) {
    let error;
    try {
      await executeRequest(request, {
        credentialLoader: async () => 'fixture-key',
        evaluateFn: input => evaluateOpenRouter(input, fetchFn),
        sdkVersion: 'openrouter-direct-v1',
      });
    } catch (caught) { error = publicError(caught); }
    assert.equal(error.error.code, code);
  }
});
