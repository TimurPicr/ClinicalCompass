export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export async function api<T>(path: string, body?: unknown, options?: { signal?: AbortSignal }): Promise<T> {
  const csrf = document.cookie.split('; ').find(row => row.startsWith('cc_csrf='))?.split('=')[1] ?? ''
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(body === undefined ? {} : { 'X-CSRF-Token': decodeURIComponent(csrf) }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: options?.signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const message = typeof data.detail === 'string' ? data.detail : 'Проверьте поля формы и повторите запрос'
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('session-expired'))
    throw new ApiError(response.status, message)
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}
