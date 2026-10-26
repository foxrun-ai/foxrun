#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { executeRequest, JevError, publicError } from './lib/core.mjs';
import { executeBatch } from './lib/batch.mjs';
import { evaluateOpenRouter } from './lib/openrouter.mjs';

const MAX_INPUT_BYTES = 4 * 1024 * 1024;
// The secret reader comes from the command path; JEV_SECRET_TOOL and JEV_SECRET_REF override it.
const SECRET_TOOL = process.env.JEV_SECRET_TOOL || 'agent-secret-read';
const SECRET_REFERENCE = process.env.JEV_SECRET_REF || 'op://Foxrun/OpenRouter/credential';

function readArguments() {
  const args = process.argv.slice(2);
  const options = {};
  let path;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--resume') options.resume = true;
    else if (['--concurrency', '--max-attempts', '--progress'].includes(arg)) {
      const value = args[++i];
      if (!value) throw new JevError('invalid_input', 'The Jev request is invalid.');
      if (arg === '--progress') options.progressPath = resolve(value);
      else options[arg === '--concurrency' ? 'concurrency' : 'maxAttempts'] = Number(value);
    } else if (arg.startsWith('--') || path) throw new JevError('invalid_input', 'The Jev request is invalid.');
    else path = arg;
  }
  return { path, options };
}

function readInput(path) {
  const data = path ? readFileSync(resolve(path)) : readFileSync(0);
  if (data.length === 0 || data.length > MAX_INPUT_BYTES) {
    throw new JevError('invalid_input', 'The Jev request is invalid.');
  }
  try {
    return JSON.parse(data.toString('utf8'));
  } catch {
    throw new JevError('invalid_input', 'The Jev request is invalid.');
  }
}

async function loadCredential() {
  try {
    const key = execFileSync(SECRET_TOOL, [SECRET_REFERENCE], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      maxBuffer: 64 * 1024,
      timeout: 10_000,
    }).trim();
    if (!key) throw new Error('empty secret');
    return key;
  } catch {
    throw new JevError('missing_credential', 'The OpenRouter credential is unavailable.');
  }
}

async function main() {
  const { path, options } = readArguments();
  const input = readInput(path);
  const scriptDirectory = dirname(fileURLToPath(import.meta.url));
  const dependencies = {
    schemaPath: join(scriptDirectory, '..', 'references', 'agent-os-migration.sql'),
  };
  if (input.action === 'evaluate' || input.action === 'batch') {
    dependencies.evaluateFn = evaluateOpenRouter;
    dependencies.credentialLoader = loadCredential;
    dependencies.sdkVersion = 'openrouter-direct-v1';
  }
  if (input.action === 'batch') {
    const result = await executeBatch(input, dependencies, options);
    if (!result.ok) process.exitCode = 1;
    return result;
  }
  if (Object.keys(options).length) throw new JevError('invalid_input', 'The Jev request is invalid.');
  return executeRequest(input, dependencies);
}

try {
  const result = await main();
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify(publicError(error), null, 2)}\n`);
  process.exitCode = 1;
}
