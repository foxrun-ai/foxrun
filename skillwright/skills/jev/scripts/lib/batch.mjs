import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { executeRequest, JevError, publicError } from './core.mjs';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const retryable = new Set(['provider_rate_limited', 'provider_failed', 'provider_timeout']);

export async function executeBatch(input, dependencies = {}, options = {}) {
  const requests = input?.requests;
  const concurrency = options.concurrency ?? 2;
  const maxAttempts = options.maxAttempts ?? 4;
  const progressPath = options.progressPath;
  if (input?.action !== 'batch' || !Array.isArray(requests) || requests.length === 0 ||
      !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 32 ||
      !Number.isInteger(maxAttempts) || maxAttempts < 1 || maxAttempts > 10 ||
      typeof progressPath !== 'string' || !progressPath.trim()) {
    throw new JevError('invalid_input', 'The Jev request is invalid.');
  }
  const ids = new Set();
  for (const request of requests) {
    if (request?.action !== 'evaluate' || typeof request.request_id !== 'string' ||
        !request.request_id.trim() || ids.has(request.request_id)) {
      throw new JevError('invalid_input', 'The Jev request is invalid.');
    }
    ids.add(request.request_id);
  }
  const succeeded = new Set();
  if (options.resume && existsSync(progressPath)) {
    for (const line of readFileSync(progressPath, 'utf8').split('\n')) {
      if (!line.trim()) continue;
      let entry;
      try { entry = JSON.parse(line); } catch { throw new JevError('invalid_input', 'The Jev request is invalid.'); }
      if (entry?.ok === true && typeof entry.request_id === 'string') succeeded.add(entry.request_id);
    }
  }
  const pending = requests.filter(request => !succeeded.has(request.request_id));
  const summary = { ok: 0, failed: 0, skipped: requests.length - pending.length,
    retried: 0, rate_limited: 0, wall_time_ms: 0 };
  const clock = options.clock ?? (() => performance.now());
  const sleep = options.sleep ?? pause;
  const random = options.random ?? Math.random;
  const started = clock();
  let cursor = 0;

  async function worker() {
    while (cursor < pending.length) {
      const request = pending[cursor++];
      let finished;
      let attempts = 0;
      let rateLimited = 0;
      while (attempts < maxAttempts) {
        attempts += 1;
        try {
          const result = await executeRequest(request, { ...dependencies, retryFailedClaim: true });
          finished = { request_id: request.request_id, ok: true, attempts, rate_limited: rateLimited, result };
          summary.ok += 1;
          break;
        } catch (error) {
          const safe = publicError(error);
          if (safe.error.code === 'provider_rate_limited') {
            rateLimited += 1;
            summary.rate_limited += 1;
          }
          if (!retryable.has(safe.error.code) || attempts === maxAttempts) {
            finished = { request_id: request.request_id, ok: false, attempts, rate_limited: rateLimited,
              error: safe.error };
            summary.failed += 1;
            break;
          }
          summary.retried += 1;
          const base = safe.error.code === 'provider_rate_limited' ? 5_000 : 1_000;
          const exponential = Math.min(60_000, base * 2 ** (attempts - 1));
          const retryAfter = safe.error.retry_after_ms ?? 0;
          await sleep(Math.max(exponential, retryAfter) + Math.floor(random() * 500));
        }
      }
      appendFileSync(progressPath, `${JSON.stringify(finished)}\n`, { encoding: 'utf8' });
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, () => worker()));
  summary.wall_time_ms = Math.max(0, Math.round(clock() - started));
  return { ok: summary.failed === 0, action: 'batch', summary, progress: progressPath };
}
