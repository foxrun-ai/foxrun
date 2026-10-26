import { readFileSync, statSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

function openDatabase(databasePath) {
  const database = new DatabaseSync(databasePath);
  database.exec('PRAGMA foreign_keys = ON');
  database.exec('PRAGMA busy_timeout = 5000');
  return database;
}

function transaction(database, operation) {
  database.exec('BEGIN IMMEDIATE');
  try {
    const result = operation();
    database.exec('COMMIT');
    return result;
  } catch (error) {
    try {
      database.exec('ROLLBACK');
    } catch {
      // Preserve the original error.
    }
    throw error;
  }
}

export function applyMigration(databasePath, schemaPath) {
  if (!statSync(databasePath).isFile()) {
    throw new Error('database path is not a file');
  }
  const database = openDatabase(databasePath);
  try {
    database.exec(readFileSync(schemaPath, 'utf8'));
  } catch (error) {
    try {
      database.exec('ROLLBACK');
    } catch {
      // The migration might have failed before its transaction began.
    }
    throw error;
  } finally {
    database.close();
  }
}

export function claimRun(databasePath, run, options = {}) {
  const database = openDatabase(databasePath);
  try {
    return transaction(database, () => {
      const existing = database
        .prepare(
          `SELECT request_id, input_sha256, status, result_json
             FROM jev_runs
            WHERE request_id = ?`,
        )
        .get(run.request_id);

      if (existing) {
        if (existing.input_sha256 !== run.input_sha256) {
          return { status: 'conflict' };
        }
        if (existing.status === 'succeeded') {
          return {
            status: 'replay',
            result: JSON.parse(existing.result_json),
          };
        }
        if (existing.status === 'failed' && options.retryFailed) {
          database.prepare(
            `UPDATE jev_runs SET status = 'running', completed_at = NULL, error_code = NULL,
              result_json = NULL, elapsed_ms = NULL
              WHERE request_id = ? AND status = 'failed'`,
          ).run(run.request_id);
          return { status: 'claimed' };
        }
        return { status: existing.status };
      }

      database
        .prepare(
          `INSERT INTO jev_runs (
             request_id, created_at, status, use_case, model_requested,
             sdk_version, request_schema_version, question_set_version,
             state_schema_version, input_sha256, question_types_json, output_ref
           ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(
          run.request_id,
          run.created_at,
          run.use_case,
          run.model_requested,
          run.sdk_version,
          run.request_schema_version,
          run.question_set_version,
          run.state_schema_version,
          run.input_sha256,
          JSON.stringify(run.question_types),
          run.output_ref,
        );
      return { status: 'claimed' };
    });
  } finally {
    database.close();
  }
}

export function finishRun(databasePath, requestId, completedAt, result) {
  const database = openDatabase(databasePath);
  try {
    const change = database
      .prepare(
        `UPDATE jev_runs
            SET completed_at = ?, status = 'succeeded', model_returned = ?,
                model_version = ?, provider_generation_id = ?, result_json = ?, elapsed_ms = ?,
                input_tokens = ?, output_tokens = ?, total_tokens = ?,
                provider_cost_amount = ?, provider_cost_currency = ?,
                provider_cost_source = ?, error_code = NULL
          WHERE request_id = ? AND status = 'running'`,
      )
      .run(
        completedAt,
        result.model.returned,
        result.model.version,
        result.provider.generation_id,
        JSON.stringify(result),
        result.timing.elapsed_ms,
        result.usage.input_tokens,
        result.usage.output_tokens,
        result.usage.total_tokens,
        result.provider_cost.amount,
        result.provider_cost.currency,
        result.provider_cost.source,
        requestId,
      );
    if (change.changes !== 1) {
      throw new Error('run claim was lost');
    }
  } finally {
    database.close();
  }
}

export function failRun(databasePath, requestId, completedAt, errorCode, elapsedMs) {
  const database = openDatabase(databasePath);
  try {
    database
      .prepare(
        `UPDATE jev_runs
            SET completed_at = ?, status = 'failed', error_code = ?, elapsed_ms = ?
          WHERE request_id = ? AND status = 'running'`,
      )
      .run(completedAt, errorCode, elapsedMs, requestId);
  } finally {
    database.close();
  }
}

export function addFeedback(databasePath, feedback) {
  const database = openDatabase(databasePath);
  try {
    database
      .prepare(
        `INSERT INTO jev_feedback (
           id, request_id, created_at, kind, assessment, fit, rationale,
           evidence_ref, note
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        feedback.id,
        feedback.request_id,
        feedback.created_at,
        feedback.kind,
        feedback.assessment,
        feedback.fit,
        feedback.rationale,
        feedback.evidence_ref,
        feedback.note,
      );
  } finally {
    database.close();
  }
}

export function getReviewStatus(databasePath, requestId) {
  const database = openDatabase(databasePath);
  try {
    const row = database
      .prepare(
        `SELECT quality_status, evidence_count
           FROM jev_run_review_status
          WHERE request_id = ?`,
      )
      .get(requestId);
    return row ?? { quality_status: 'unchecked', evidence_count: 0 };
  } finally {
    database.close();
  }
}
