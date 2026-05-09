type UnauthorizedHandler = (message?: string) => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

function withBasePath(url: string): string {
  if (!url.startsWith('/')) return url;
  return `${import.meta.env.BASE_URL.replace(/\/$/, '')}${url}`;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = typeof handler === 'function' ? handler : null;
}

export async function apiFetch<T>(url: string, options: RequestInit = {}, action = 'request'): Promise<T> {
  let response: Response;
  try {
    response = await fetch(withBasePath(url), {
      credentials: 'same-origin',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {})
      }
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to fetch';
    throw new Error(`Network error while ${action}: ${message}`);
  }

  const contentType = response.headers.get('content-type') || '';
  const bodyText = await response.text();
  let body: unknown = null;

  if (bodyText && contentType.includes('application/json')) {
    try {
      body = JSON.parse(bodyText);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    if (response.status === 401) {
      unauthorizedHandler?.('Session expired. Please enter the access key.');
      throw new ApiError('Session expired. Please enter the access key.', response.status, body);
    }

    const data = body as { detail?: string; error?: string; message?: string } | null;
    const message = data?.detail || data?.error || data?.message || bodyText || `${action} failed`;
    throw new ApiError(`${message}${response.status ? ` (${response.status})` : ''}`, response.status, body);
  }

  if (body === null) {
    return bodyText as T;
  }

  return body as T;
}

