/** file_finder API 客户端（统一 JSON 协商，response_v2 自动降级） */

export const API_BASE = '/api/file_finder'

export class ApiError extends Error {
  constructor(status, msg) {
    super(msg || `HTTP ${status}`)
    this.status = status
  }
}

export async function api(path, opts = {}) {
  const { headers, ...rest } = opts
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), opts.timeout || 30000)
  try {
    const res = await fetch(API_BASE + path, {
      headers: { Accept: 'application/json', ...(headers || {}) },
      signal: controller.signal,
      ...rest,
    })
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) {
      const body = await res.json()
      if (!res.ok || (body && typeof body === 'object' && body.code !== undefined && body.code !== 0)) {
        throw new ApiError(res.status, body?.msg || body?.detail || res.statusText)
      }
      return body
    }
    if (!res.ok) throw new ApiError(res.status, res.statusText)
    return res
  } finally {
    clearTimeout(timer)
  }
}

export const apiRoots = {
  list: () => api('/roots'),
  add: path => api('/roots', { method: 'POST', body: JSON.stringify({ path }), headers: { 'Content-Type': 'application/json' } }),
  remove: id => api(`/roots/${id}`, { method: 'DELETE' }),
  setEnabled: (id, enabled) => api(`/roots/${id}/enable`, { method: 'POST', body: JSON.stringify({ enabled }), headers: { 'Content-Type': 'application/json' } }),
  scan: (id, mode = 'incremental') => api(`/roots/${id}/scan`, { method: 'POST', body: JSON.stringify({ mode }), headers: { 'Content-Type': 'application/json' } }),
}

export const apiSearch = (params) => api('/search?' + new URLSearchParams(params).toString())

export const apiFavorites = {
  list: (params) => api('/favorites?' + new URLSearchParams(params).toString()),
  toggle: (fileId) => api('/favorites/toggle', { method: 'POST', body: JSON.stringify({ file_id: fileId }), headers: { 'Content-Type': 'application/json' } }),
  remove: (favId) => api(`/favorites/${favId}`, { method: 'DELETE' }),
  pruneMissing: () => api('/favorites/prune-missing', { method: 'POST' }),
}

export const apiFiles = {
  detail: (id) => api(`/files/${id}`),
  remove: (id) => api(`/files/${id}`, { method: 'DELETE' }),
  previewInfo: (id) => api(`/files/${id}/preview-info`),
  downloadUrl: (id) => `${API_BASE}/files/${id}/download`,
  thumbUrl: (id, size = 256) => `${API_BASE}/files/${id}/thumb?size=${size}`,
  previewUrl: (id) => `${API_BASE}/files/${id}/preview`,
}

export async function fetchTextPreview(id, signal) {
  const res = await fetch(`${API_BASE}/files/${id}/preview`, {
    headers: { Accept: 'text/plain' },
    signal,
  })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const content = await res.text()
  return {
    content,
    encoding: res.headers.get('X-Preview-Encoding') || 'utf-8',
    truncated: res.headers.get('X-Preview-Truncated') === '1',
  }
}

export const apiCollect = {
  plan: () => api('/collect/plan'),
  run: (opts) => api('/collect/run', {
    method: 'POST',
    body: JSON.stringify({ copy: true, cleanup: true, remove_empty_roots: true, confirm: true, ...opts }),
    headers: { 'Content-Type': 'application/json' },
  }),
}

export const apiStats = () => api('/stats')
export const apiTasks = {
  list: () => api('/tasks'),
  detail: (id) => api(`/tasks/${id}`),
  cancel: (id) => api(`/tasks/${id}/cancel`, { method: 'POST' }),
  eventsUrl: (id) => `${API_BASE}/tasks/${id}/events`,
}
