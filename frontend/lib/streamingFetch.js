import { getApiUrl } from './api';

/**
 * Stream an SSE response from a POST endpoint using fetch + ReadableStream.
 *
 * @param {string} path - API path (e.g. '/ask-stream')
 * @param {object} body - JSON body to send
 * @param {object} callbacks - { onToken(text), onDone(data), onError(data) }
 * @param {AbortSignal} [signal] - Optional AbortController signal to cancel
 * @returns {Promise<void>}
 */
export async function streamAsk(path, body, callbacks, signal) {
  const { onToken, onDone, onError } = callbacks;
  const url = `${getApiUrl()}${path}`;

  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') return;
    onError?.({ message: err.message, code: 'network_error' });
    return;
  }

  if (response.status === 401) {
    if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
      window.location.href = '/login';
    }
    return;
  }
  if (response.status === 403) {
    if (typeof window !== 'undefined' && !window.location.pathname.includes('/setup-2fa')) {
      window.location.href = '/setup-2fa';
    }
    return;
  }
  if (response.status === 429) {
    onError?.({ message: 'Too many requests. Please try again later.', code: 'rate_limit' });
    return;
  }
  if (!response.ok) {
    onError?.({ message: `HTTP ${response.status}`, code: 'http_error' });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const parts = buffer.split('\n\n');
      // Keep the last part as it may be incomplete
      buffer = parts.pop() || '';

      for (const part of parts) {
        if (!part.trim()) continue;

        let eventType = '';
        let dataStr = '';

        for (const line of part.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7);
          } else if (line.startsWith('data: ')) {
            dataStr = line.slice(6);
          }
        }

        if (!eventType || !dataStr) continue;

        let data;
        try {
          data = JSON.parse(dataStr);
        } catch {
          continue;
        }

        if (eventType === 'token') {
          onToken?.(data.t || '');
        } else if (eventType === 'done') {
          onDone?.(data);
        } else if (eventType === 'error') {
          onError?.(data);
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    onError?.({ message: err.message, code: 'stream_error' });
  }
}
