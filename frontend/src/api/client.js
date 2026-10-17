/**
 * 后端接口封装（唯一出口）。
 * 契约：docs/api-contract.md —— 字段名、空结果结构、降级形态都以它为准。
 *
 * 组件里不要直接写 fetch：所有异常处理、空结果判定都集中在这里。
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'NETWORK_ERROR', requestId = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('无法连接后端服务，请确认后端已启动（默认 8000 端口）', { code: 'NETWORK_ERROR' })
  }

  const text = await response.text()
  const payload = text ? safeJson(text) : null

  if (!response.ok) {
    const detail = payload?.error
    throw new ApiError(detail?.message || `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      code: detail?.code || 'HTTP_ERROR',
      requestId: detail?.request_id ?? null,
    })
  }
  return payload
}

function safeJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** 空结果判定：契约规定未收录姓氏返回 200 + coverage.status = not_in_corpus */
export function isEmptyCoverage(coverage) {
  return !coverage || coverage.status === 'not_in_corpus'
}

export const api = {
  health: () => request('/api/health'),
  surnameOverview: (name) => request(`/api/surnames/${encodeURIComponent(name)}`),
  earliest: (name) => request(`/api/surnames/${encodeURIComponent(name)}/earliest`),
  commanderies: (name) => request(`/api/surnames/${encodeURIComponent(name)}/commanderies`),
  migrations: (name) => request(`/api/surnames/${encodeURIComponent(name)}/migrations`),
  corpusChecks: (name) => request(`/api/surnames/${encodeURIComponent(name)}/corpus-checks`),
  ask: (payload) => request('/api/ask', { method: 'POST', body: payload }),
}