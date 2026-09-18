/** 任务追踪（SSE + 轮询兜底），供 TaskBar 与全局共用 */
import { ref } from 'vue'
import { apiTasks } from './api'

export const tasks = ref([])
const esMap = new Map()

export function trackTask(taskId) {
  if (!taskId || esMap.has(taskId)) return
  const t = {
    task_id: taskId, name: '任务', stage: '等待中', percent: 0,
    status: 'PENDING', finished: false, error: null, updated_at: 0,
  }
  const sync = data => {
    Object.assign(t, data)
    t.finished = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(t.status)
    if (t.finished) t.percent = Math.max(t.percent || 0, 100)
  }
  // 先拉一次详情兜底（SSE 可能尚未建立）
  apiTasks.detail(taskId).then(r => { sync(r.data) }).catch(() => {})
  const es = new EventSource(apiTasks.eventsUrl(taskId))
  esMap.set(taskId, es)
  es.onmessage = e => { try { sync(JSON.parse(e.data)) } catch {} }
  es.addEventListener('progress', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('done', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('error', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('cancelled', e => { try { sync(JSON.parse(e.data)) } catch {} })
  // 轮询兜底：SSE 断开/代理缓冲时仍能收敛
  const timer = setInterval(async () => {
    if (t.finished) { clearInterval(timer); es.close(); esMap.delete(taskId); return }
    try {
      const r = await apiTasks.detail(taskId)
      sync(r.data)
    } catch { t.finished = true }
  }, 3000)
  tasks.value.push(t)
}

export async function cancelTask(taskId) {
  try { await apiTasks.cancel(taskId) } catch {}
}

export function activeTaskCount() {
  return tasks.value.filter(t => !t.finished).length
}
