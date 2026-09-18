/** 文件大小格式化 */
export function formatSize(bytes) {
  if (bytes === null || bytes === undefined || isNaN(bytes)) return '-'
  if (bytes < 1024) return bytes + ' B'
  const units = ['KB', 'MB', 'GB', 'TB', 'PB']
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2) + ' ' + units[i]
}

/** 时间戳格式化 */
export function formatDate(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function formatDateShort(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** 查询参数序列化（跳过空值） */
export function qs(params) {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === '') continue
    usp.set(k, v)
  }
  return usp.toString()
}
