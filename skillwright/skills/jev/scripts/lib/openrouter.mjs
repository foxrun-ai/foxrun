export const OPENROUTER_URL = 'https://openrouter.ai/api/alpha/decisions';

export async function evaluateOpenRouter({ model, state, questions, credential, abortSignal }, fetchFn = fetch) {
  const providerQuestions = Object.fromEntries(Object.entries(questions).map(([id, question]) => [
    id,
    question.type === 'boolean' ? { ...question, type: 'noul' } : question,
  ]));
  const response = await fetchFn(OPENROUTER_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${credential}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ model, state, questions: providerQuestions }),
    signal: abortSignal,
  });
  if (!response.ok) {
    const error = new Error('OpenRouter request failed.');
    error.statusCode = response.status;
    error.responseHeaders = response.headers;
    throw error;
  }
  const result = await response.json();
  if (result?.answers && typeof result.answers === 'object' && !Array.isArray(result.answers)) {
    result.answers = Object.fromEntries(Object.entries(result.answers).map(([id, answer]) => [
      id,
      answer?.type === 'noul'
        ? { type: 'boolean', probability: answer.noul, ...(answer.confidence === undefined ? {} : { confidence: answer.confidence }) }
        : answer,
    ]));
  }
  return result;
}
