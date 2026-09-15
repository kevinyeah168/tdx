const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function isApiNotFound(error: unknown): boolean {
  return error instanceof Error && /\b404\b/.test(error.message)
}

export async function apiGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value)
    }
  }
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  params?: Record<string, string>,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value)
    }
  }
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}
