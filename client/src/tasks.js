/** 任务追踪（SSE + 高频 300ms 轮询兜底 + 客户端平滑进度插值），供 TaskBar 与全局共用 */
import { ref } from 'vue'
import { apiTasks } from './api'

export const tasks = ref([])
const esMap = new Map()

// 全局平滑动画帧循环：让每个任务的 displayPercent 平滑连续递增，杜绝 0% 到 100% 的突然跳跃
let animTimer = null
function ensureAnimLoop() {
  if (animTimer) return
  animTimer = setInterval(() => {
    let hasActive = false
    for (const t of tasks.value) {
      if (t.displayPercent === undefined) t.displayPercent = 0
      const target = typeof t.percent === 'number' ? t.percent : 0

      if (t.finished) {
        // 完成态：快速平滑推至 100%
        if (t.displayPercent < 100) {
          t.displayPercent = Math.min(100, t.displayPercent + Math.max(1.5, (100 - t.displayPercent) * 0.3))
          hasActive = true
        }
      } else {
        hasActive = true
        if (t.displayPercent < target) {
          // 平滑追赶目标百分比
          const step = Math.max(0.4, (target - t.displayPercent) * 0.22)
          t.displayPercent = Math.min(target, t.displayPercent + step)
        } else if (t.displayPercent >= target && t.status === 'RUNNING' && t.displayPercent < 90) {
          // 运行中阶段：如果没有新数据到达，轻微蠕动递增（每秒约 1.2%），给用户持续进行的活体反馈
          t.displayPercent = Math.min(90, t.displayPercent + 0.05)
        }
      }
    }
    if (!hasActive && tasks.value.every(t => t.finished && (t.displayPercent || 0) >= 100)) {
      clearInterval(animTimer)
      animTimer = null
    }
  }, 40)
}

export function trackTask(taskId, onDone) {
  if (!taskId || esMap.has(taskId)) return
  let doneCb = onDone
  const t = {
    task_id: taskId, name: '任务', stage: '准备中...',
    percent: 2, displayPercent: 1,
    status: 'PENDING', finished: false, error: null, updated_at: Date.now(),
  }
  tasks.value.push(t)
  ensureAnimLoop()

  const sync = data => {
    if (!data) return
    const prevFinished = t.finished
    Object.assign(t, data)
    t.finished = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(t.status)
    if (t.finished) {
      t.percent = 100
      if (!prevFinished) {
        if (doneCb) {
          setTimeout(() => {
            if (doneCb) {
              doneCb(t)
              doneCb = null
            }
          }, 320)
        }
        // 自动平滑淡出消失：成功完成保留 3.5 秒，已取消保留 2.5 秒，失败保留 8 秒
        const autoDismissMs = t.status === 'COMPLETED' ? 3500 : (t.status === 'CANCELLED' ? 2500 : 8000)
        setTimeout(() => {
          removeTask(t.task_id)
        }, autoDismissMs)
      }
    }
  }

  // 1. 立即拉取一次详情（低延迟初值）
  apiTasks.detail(taskId).then(r => { sync(r.data) }).catch(() => {})

  // 2. 建立 SSE 长连接
  const es = new EventSource(apiTasks.eventsUrl(taskId))
  esMap.set(taskId, es)
  es.onmessage = e => { try { sync(JSON.parse(e.data)) } catch {} }
  es.addEventListener('snapshot', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('progress', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('done', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('error', e => { try { sync(JSON.parse(e.data)) } catch {} })
  es.addEventListener('cancelled', e => { try { sync(JSON.parse(e.data)) } catch {} })

  // 3. 高频轮询兜底（300ms 间隔，彻底规避 SSE 建立延迟导致的阶段性空白）
  const timer = setInterval(async () => {
    if (t.finished) {
      clearInterval(timer)
      es.close()
      esMap.delete(taskId)
      return
    }
    try {
      const r = await apiTasks.detail(taskId)
      sync(r.data)
    } catch {
      t.finished = true
    }
  }, 300)
}

export function removeTask(taskId) {
  const es = esMap.get(taskId)
  if (es) {
    try { es.close() } catch {}
    esMap.delete(taskId)
  }
  const idx = tasks.value.findIndex(t => t.task_id === taskId)
  if (idx >= 0) {
    tasks.value.splice(idx, 1)
  }
}

export async function loadActiveTasks() {
  try {
    const r = await apiTasks.list()
    const list = r?.data || []
    for (const it of list) {
      if (['PENDING', 'RUNNING'].includes(it.status)) {
        trackTask(it.task_id)
      }
    }
  } catch { /* noop */ }
}

export async function cancelTask(taskId) {
  try { await apiTasks.cancel(taskId) } catch {}
}

export function clearFinishedTasks() {
  for (const t of tasks.value.filter(it => it.finished)) {
    removeTask(t.task_id)
  }
}

export function activeTaskCount() {
  return tasks.value.filter(t => !t.finished).length
}
