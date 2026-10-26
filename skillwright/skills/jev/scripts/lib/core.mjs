import { createHash, randomUUID } from 'node:crypto';
import * as defaultStorage from './storage.mjs';

export const MODEL_ID = '~typesafe/jev-latest';

export class JevError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'JevError';
    this.code = code;
    this.check = details.check;
    this.retryAfterMs = details.retryAfterMs;
  }
}

const PUBLIC_MESSAGES = {
  invalid_input: 'The Jev request is invalid.',
  missing_credential: 'The OpenRouter credential is unavailable.',
  request_id_conflict: 'This request_id already belongs to different input.',
  request_in_progress: 'This request_id is already running.',
  previous_run_failed: 'This request_id already has a failed run. Use a new request_id.',
  provider_authentication_failed: 'OpenRouter rejected the credential.',
  provider_rate_limited: 'OpenRouter rate-limited the request.',
  provider_timeout: 'The Jev request timed out.',
  provider_failed: 'The Jev provider request failed.',
  storage_failed: 'The Jev record could not be stored.',
  storage_not_migrated: 'This store has no Jev tables. Run the migrate action on it first.',
  migration_failed: 'The Jev schema migration failed.',
  feedback_failed: 'The Jev feedback record could not be stored.',
  internal_error: 'The Jev runner failed.',
};

function fail(code) {
  throw new JevError(code, PUBLIC_MESSAGES[code]);
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isJson(value, ancestors = new Set()) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object') return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every(item => isJson(item, ancestors))
    : Object.getOwnPropertySymbols(value).length === 0 &&
      Object.values(value).every(item => isJson(item, ancestors));
  ancestors.delete(value);
  return valid;
}

function isEvaluationInput(value) {
  return (typeof value === 'string' || Array.isArray(value) || isObject(value)) && isJson(value);
}

function nonempty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function validateQuestions(questions) {
  if (!isObject(questions) || Object.keys(questions).length === 0) fail('invalid_input');
  for (const [id, question] of Object.entries(questions)) {
    if (!nonempty(id) || !isObject(question) || !isEvaluationInput(question.instructions)) {
      fail('invalid_input');
    }
    if (question.type === 'choice') {
      if (!isObject(question.criteria) || Object.keys(question.criteria).length === 0) fail('invalid_input');
      if (!Object.values(question.criteria).every(value => value === null || isEvaluationInput(value))) {
        fail('invalid_input');
      }
    } else if (question.type === 'score') {
      if (!Array.isArray(question.criteria) || question.criteria.length < 2) fail('invalid_input');
      if (!question.criteria.every(value => value === null || isEvaluationInput(value))) fail('invalid_input');
    } else if (question.type === 'boolean') {
      if (question.criteria !== undefined) {
        if (!isObject(question.criteria)) fail('invalid_input');
        if (Object.keys(question.criteria).some(key => key !== 'true' && key !== 'false')) fail('invalid_input');
        if (!Object.values(question.criteria).every(value => value === null || isEvaluationInput(value))) {
          fail('invalid_input');
        }
      }
    } else {
      fail('invalid_input');
    }
  }
}

function validateEvaluateInput(input) {
  if (!isObject(input) || input.action !== 'evaluate') fail('invalid_input');
  for (const field of [
    'request_id',
    'use_case',
    'request_schema_version',
    'question_set_version',
    'state_schema_version',
  ]) {
    if (!nonempty(input[field])) fail('invalid_input');
  }
  if (!isEvaluationInput(input.state)) fail('invalid_input');
  validateQuestions(input.questions);
  if (input.output_ref !== undefined && !nonempty(input.output_ref)) fail('invalid_input');
  if (input.storage !== undefined) {
    if (!isObject(input.storage) || !nonempty(input.storage.database)) fail('invalid_input');
    if (input.storage.required !== undefined && typeof input.storage.required !== 'boolean') fail('invalid_input');
  }
}

function probability(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= -1e-6 && value <= 1 + 1e-6;
}

function providerCheck(name) {
  throw new JevError('provider_failed', PUBLIC_MESSAGES.provider_failed, { check: name });
}

function normalizedProbability(value) {
  return Math.min(1, Math.max(0, value));
}

function normalizedAnswers(questions, answers) {
  if (!isObject(answers) || Object.keys(answers).length !== Object.keys(questions).length) {
    providerCheck('answer_count');
  }
  const normalized = {};
  for (const [id, question] of Object.entries(questions)) {
    const answer = answers[id];
    if (!isObject(answer) || answer.type !== question.type) providerCheck('answer_type');
    if (question.type === 'choice') {
      if (!nonempty(answer.choice) || !Object.hasOwn(question.criteria, answer.choice)) providerCheck('choice_value');
      const item = { type: 'choice', choice: answer.choice };
      if (answer.probabilities !== undefined) {
        const keys = Object.keys(question.criteria);
        if (!isObject(answer.probabilities) ||
            keys.some(key => !probability(answer.probabilities[key])) ||
            Object.keys(answer.probabilities).length !== keys.length) providerCheck('choice_probabilities');
        item.probabilities = Object.fromEntries(keys.map(key => [key, normalizedProbability(answer.probabilities[key])]));
      }
      if (answer.confidence !== undefined) {
        if (!probability(answer.confidence)) providerCheck('answer_confidence');
        item.confidence = normalizedProbability(answer.confidence);
      }
      normalized[id] = item;
    } else if (question.type === 'score') {
      if (typeof answer.score !== 'number' || !Number.isFinite(answer.score) ||
          answer.score < 0 || answer.score > question.criteria.length - 1) providerCheck('score_value');
      const item = { type: 'score', score: answer.score };
      if (answer.probabilities !== undefined) {
        const keys = question.criteria.map((_, index) => String(index));
        if (!isObject(answer.probabilities) ||
            keys.some(key => !probability(answer.probabilities[key])) ||
            Object.keys(answer.probabilities).length !== keys.length) providerCheck('score_probabilities');
        item.probabilities = Object.fromEntries(keys.map(key => [key, normalizedProbability(answer.probabilities[key])]));
      }
      if (answer.confidence !== undefined) {
        if (!probability(answer.confidence)) providerCheck('answer_confidence');
        item.confidence = normalizedProbability(answer.confidence);
      }
      normalized[id] = item;
    } else {
      if (!probability(answer.probability)) providerCheck('boolean_probability');
      const item = { type: 'boolean', probability: normalizedProbability(answer.probability) };
      if (answer.confidence !== undefined) {
        if (!probability(answer.confidence)) providerCheck('answer_confidence');
        item.confidence = normalizedProbability(answer.confidence);
      }
      normalized[id] = item;
    }
  }
  return normalized;
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function safeIdentifier(value) {
  return typeof value === 'string' && /^[A-Za-z0-9._:/-]{1,200}$/.test(value) ? value : null;
}

function sanitizeWarnings(warnings) {
  if (!Array.isArray(warnings)) return [];
  const allowed = new Set(['unsupported', 'compatibility', 'deprecated', 'other']);
  return warnings.map(warning => ({
    type: isObject(warning) && allowed.has(warning.type) ? warning.type : 'unknown',
  }));
}

function actualProviderCost(result) {
  const cost = result?.usage?.cost;
  const parsedCost =
    typeof cost === 'number'
      ? cost
      : typeof cost === 'string' && /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(cost)
        ? Number(cost)
        : null;
  if (parsedCost !== null && Number.isFinite(parsedCost) && parsedCost >= 0) {
    return {
      status: 'known',
      amount: parsedCost,
      currency: 'USD',
      source: 'usage.cost',
    };
  }
  return { status: 'unknown', amount: null, currency: null, source: null };
}

function classifyProviderError(error) {
  if (error instanceof JevError) return error;
  const status = error?.statusCode ?? error?.status;
  if (status === 401 || status === 403) return new JevError('provider_authentication_failed', PUBLIC_MESSAGES.provider_authentication_failed);
  if (status === 429) {
    const headers = error?.responseHeaders ?? error?.headers ?? error?.response?.headers;
    const raw = typeof headers?.get === 'function' ? headers.get('retry-after') :
      headers?.['retry-after'] ?? headers?.['Retry-After'];
    const seconds = typeof raw === 'string' && /^\d+(?:\.\d+)?$/.test(raw.trim()) ? Number(raw) : null;
    const date = typeof raw === 'string' && seconds === null ? Date.parse(raw) : NaN;
    const retryAfterMs = seconds !== null ? seconds * 1000 : Number.isFinite(date) ? Math.max(0, date - Date.now()) : undefined;
    return new JevError('provider_rate_limited', PUBLIC_MESSAGES.provider_rate_limited, {
      retryAfterMs: Number.isFinite(retryAfterMs) ? retryAfterMs : undefined,
    });
  }
  if (error?.name === 'AbortError' || error?.name === 'TimeoutError' || error?.code === 'ETIMEDOUT' ||
      error?.reason === 'abort' || error?.lastError?.name === 'AbortError' ||
      error?.lastError?.name === 'TimeoutError') {
    return new JevError('provider_timeout', PUBLIC_MESSAGES.provider_timeout);
  }
  return new JevError('provider_failed', PUBLIC_MESSAGES.provider_failed);
}

function storageFailure(code = 'storage_failed') {
  return { status: 'failed', error: { code, message: PUBLIC_MESSAGES[code] } };
}

// The tables and the view that references/agent-os-migration.sql creates. SQLite reports a
// missing one as "no such table: <name>". Migrate fixes only these; evaluation never creates them.
const MISSING_JEV_SCHEMA = /^no such table: (?:main\.)?(?:jev_runs|jev_feedback|jev_run_review_status)$/;

function storageErrorCode(error) {
  return typeof error?.message === 'string' && MISSING_JEV_SCHEMA.test(error.message)
    ? 'storage_not_migrated'
    : 'storage_failed';
}

async function evaluate(input, dependencies) {
  validateEvaluateInput(input);
  const storage = dependencies.storage ?? defaultStorage;
  const now = dependencies.now ?? (() => new Date());
  const clock = dependencies.clock ?? (() => performance.now());
  const createdAt = now().toISOString();
  const questionTypes = Object.fromEntries(
    Object.entries(input.questions).map(([id, question]) => [id, question.type]),
  );
  const inputSha256 = createHash('sha256')
    .update(
      stableJson({
        model: MODEL_ID,
        use_case: input.use_case,
        request_schema_version: input.request_schema_version,
        question_set_version: input.question_set_version,
        state_schema_version: input.state_schema_version,
        state: input.state,
        questions: input.questions,
      }),
    )
    .digest('hex');
  const storageRequired = input.storage?.required ?? true;
  let recording = { status: 'not_requested' };
  let claimed = false;

  if (input.storage) {
    try {
      const claim = storage.claimRun(input.storage.database, {
        request_id: input.request_id,
        created_at: createdAt,
        use_case: input.use_case,
        model_requested: MODEL_ID,
        sdk_version: dependencies.sdkVersion,
        request_schema_version: input.request_schema_version,
        question_set_version: input.question_set_version,
        state_schema_version: input.state_schema_version,
        input_sha256: inputSha256,
        question_types: questionTypes,
        output_ref: input.output_ref ?? null,
      }, { retryFailed: dependencies.retryFailedClaim === true });
      if (claim.status === 'conflict') fail('request_id_conflict');
      if (claim.status === 'running') fail('request_in_progress');
      if (claim.status === 'failed') fail('previous_run_failed');
      if (claim.status === 'replay') {
        const review = storage.getReviewStatus(input.storage.database, input.request_id);
        return {
          ok: true,
          ...claim.result,
          quality: {
            status: review.quality_status,
            evidence_count: Number(review.evidence_count),
          },
          recording: { status: 'stored', idempotent_replay: true },
        };
      }
      claimed = true;
      recording = { status: 'pending' };
    } catch (error) {
      if (error instanceof JevError) throw error;
      const code = storageErrorCode(error);
      if (storageRequired) fail(code);
      recording = storageFailure(code);
    }
  }

  const started = clock();
  try {
    const key = await dependencies.credentialLoader();
    if (!nonempty(key)) fail('missing_credential');
    const providerResult = await dependencies.evaluateFn({
      model: MODEL_ID,
      state: input.state,
      questions: input.questions,
      credential: key,
      abortSignal: AbortSignal.timeout(dependencies.timeoutMs ?? 60_000),
    });
    const elapsedMs = Math.max(0, Math.round(clock() - started));
    const inputTokens = numberOrNull(providerResult?.usage?.input_tokens)
      ?? numberOrNull(providerResult?.usage?.prompt_tokens);
    const outputTokens = numberOrNull(providerResult?.usage?.output_tokens)
      ?? numberOrNull(providerResult?.usage?.completion_tokens);
    const normalized = {
      request_id: input.request_id,
      use_case: input.use_case,
      input_sha256: inputSha256,
      schemas: {
        request: input.request_schema_version,
        state: input.state_schema_version,
        questions: input.question_set_version,
      },
      question_types: questionTypes,
      answers: normalizedAnswers(input.questions, providerResult?.answers),
      model: {
        requested: MODEL_ID,
        returned: safeIdentifier(providerResult?.model),
        version: safeIdentifier(providerResult?.modelVersion),
      },
      provider: {
        generation_id: safeIdentifier(providerResult?.id),
      },
      sdk_version: dependencies.sdkVersion,
      timing: { elapsed_ms: elapsedMs },
      usage: {
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: inputTokens !== null && outputTokens !== null
          ? inputTokens + outputTokens
          : numberOrNull(providerResult?.usage?.total_tokens),
      },
      provider_cost: actualProviderCost(providerResult),
      warnings: sanitizeWarnings(providerResult?.warnings),
      output_ref: input.output_ref ?? null,
      quality: { status: 'unchecked', evidence_count: 0 },
    };

    if (claimed) {
      try {
        storage.finishRun(input.storage.database, input.request_id, now().toISOString(), normalized);
        recording = { status: 'stored', idempotent_replay: false };
      } catch {
        recording = storageFailure();
      }
    }
    return { ok: true, ...normalized, recording };
  } catch (error) {
    const safeError = classifyProviderError(error);
    if (claimed) {
      try {
        storage.failRun(
          input.storage.database,
          input.request_id,
          now().toISOString(),
          safeError.code,
          Math.max(0, Math.round(clock() - started)),
        );
      } catch {
        // The public provider error remains more useful than a second storage error.
      }
    }
    throw safeError;
  }
}

function validateFeedback(input) {
  if (!isObject(input) || input.action !== 'feedback' || !nonempty(input.database) ||
      !nonempty(input.request_id) || !['review', 'correction', 'outcome'].includes(input.kind) ||
      !['accepted', 'rejected', 'mixed', 'informational'].includes(input.assessment) ||
      (input.fit !== undefined && !['fit', 'uncertain', 'not_fit'].includes(input.fit)) ||
      (input.fit !== undefined && !nonempty(input.rationale)) ||
      (input.rationale !== undefined && typeof input.rationale !== 'string') ||
      !nonempty(input.evidence_ref) ||
      (input.note !== undefined && typeof input.note !== 'string')) fail('invalid_input');
}

function feedback(input, dependencies) {
  validateFeedback(input);
  const storage = dependencies.storage ?? defaultStorage;
  const now = dependencies.now ?? (() => new Date());
  const id = nonempty(input.feedback_id) ? input.feedback_id : randomUUID();
  try {
    storage.addFeedback(input.database, {
      id,
      request_id: input.request_id,
      created_at: now().toISOString(),
      kind: input.kind,
      assessment: input.assessment,
      fit: input.fit ?? null,
      rationale: input.rationale ?? null,
      evidence_ref: input.evidence_ref,
      note: input.note ?? null,
    });
    const review = storage.getReviewStatus(input.database, input.request_id);
    return {
      ok: true,
      action: 'feedback',
      feedback_id: id,
      request_id: input.request_id,
      quality: {
        status: review.quality_status,
        evidence_count: Number(review.evidence_count),
      },
    };
  } catch {
    fail('feedback_failed');
  }
}

function migrate(input, dependencies) {
  if (!isObject(input) || input.action !== 'migrate' || !nonempty(input.database)) fail('invalid_input');
  const storage = dependencies.storage ?? defaultStorage;
  try {
    storage.applyMigration(input.database, dependencies.schemaPath);
    return { ok: true, action: 'migrate', schema: 'jev-v1', database: input.database };
  } catch {
    fail('migration_failed');
  }
}

export async function executeRequest(input, dependencies = {}) {
  if (!isObject(input) || !nonempty(input.action)) fail('invalid_input');
  if (input.action === 'evaluate') {
    if (typeof dependencies.evaluateFn !== 'function' ||
        typeof dependencies.credentialLoader !== 'function' ||
        !nonempty(dependencies.sdkVersion)) fail('internal_error');
    return evaluate(input, dependencies);
  }
  if (input.action === 'feedback') return feedback(input, dependencies);
  if (input.action === 'migrate') return migrate(input, dependencies);
  fail('invalid_input');
}

export function publicError(error) {
  if (error instanceof JevError) {
    return { ok: false, error: {
      code: error.code, message: error.message,
      ...(error.check ? { check: error.check } : {}),
      ...(error.retryAfterMs !== undefined ? { retry_after_ms: error.retryAfterMs } : {}),
    } };
  }
  return { ok: false, error: { code: 'internal_error', message: PUBLIC_MESSAGES.internal_error } };
}
