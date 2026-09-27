<!--
VirtualList 虚拟滚动 + 分页窗口引擎（性能核心）
================================================
- 只渲染可视区 ± bufferRows 的单元格（小/中/大图网格或表格均复用本组件）
- 按页拉取（pageSize 条/页），远离可视区的页自动释放，缓存页数有上限
- 数据以非响应式 Map 存储，仅用 version 计数触发重渲染，避免深响应开销
-->
<template>
  <div ref="viewportEl" class="vl-viewport" @scroll.passive="onScroll">
    <div class="vl-canvas" :style="{ height: canvasHeight + 'px' }">
      <div
        v-for="cell in visibleCells"
        :key="cell.index"
        class="vl-cell"
        :style="cellStyle(cell)"
        :ref="(el) => trackCell(el, cell)"
      >
        <slot name="item" :item="cell.item" :index="cell.index" :row="cell.row" :col="cell.col" :loading="!cell.item"></slot>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'

const props = defineProps({
  total: { type: Number, default: 0 },
  pageSize: { type: Number, default: 300 },
  fetchPage: { type: Function, required: true },   // (pageIndex) => Promise<{total, items}>
  grid: { type: Boolean, default: true },          // false = 表格（单列）
  colWidth: { type: Number, default: 216 },
  rowHeight: { type: Number, default: 188 },
  bufferRows: { type: Number, default: 8 },        // 可视区上下缓冲行数
  maxCachedPages: { type: Number, default: 16 },
})

const emit = defineEmits(['total-update'])

const viewportEl = ref(null)
const scrollTop = ref(0)
const viewportH = ref(600)
const viewportW = ref(800)
const version = ref(0)

const pages = new Map()       // pageIndex -> items[]
const inflight = new Map()    // pageIndex -> Promise
const cellRefs = new Map()    // cell.index -> { el, item }（框选 / 范围选择用，随渲染实时更新）
let mutationSeq = 0           // 数据变更代次：删除/清空后丢弃过期页响应

function trackCell(el, cell) {
  if (el) cellRefs.set(cell.index, { el, item: cell.item })
  else cellRefs.delete(cell.index)
}

const cols = computed(() => (props.grid ? Math.max(1, Math.floor(viewportW.value / props.colWidth)) : 1))
const rows = computed(() => Math.ceil(Math.max(0, props.total) / cols.value))
const canvasHeight = computed(() => rows.value * props.rowHeight)

const pageOf = idx => Math.floor(idx / props.pageSize)

function fetchAndCache(page, force) {
  if (!force && (pages.has(page) || inflight.has(page))) return inflight.get(page)
  const seq = mutationSeq
  const p = Promise.resolve(props.fetchPage(page))
    .then(res => {
      if (seq !== mutationSeq) return res   // 期间发生删除/清空：丢弃过期响应
      pages.set(page, res?.items || [])
      if (typeof res?.total === 'number') emit('total-update', res.total)
      return res
    })
    .catch(() => { if (seq === mutationSeq) pages.set(page, []) })
    .finally(() => {
      inflight.delete(page)
      version.value++
    })
  inflight.set(page, p)
  return p
}

// 批量确保指定页码区间的数据全部加载入内存（供复制序列、完整性校验等使用）
async function ensurePagesLoaded(minPage, maxPage) {
  const promises = []
  for (let p = minPage; p <= maxPage; p++) {
    if (pages.has(p)) continue
    if (inflight.has(p)) {
      promises.push(inflight.get(p))
    } else {
      const pr = fetchAndCache(p)
      if (pr) promises.push(pr)
    }
  }
  if (promises.length) await Promise.all(promises)
}

// 局部数据变更：链式补位，删除瞬间不闪烁、翻页无空洞
// 删除点页移除被删项，后续每页首项逐页前移补位（已加载页全部保留渲染）；
// 仅当补位链尾仍有缺口（其后的数据尚未加载）时，才让最后一段失效，滚动到时重拉。
// totalHint 可选：直接更新总数（后端返回的实际变化数，含目录子树）
function removeAndRefresh(ids, totalHint) {
  const set = new Set(ids)
  const matchId = it => it && (set.has(it.id) || (it.fav_id && set.has(it.fav_id)))
  let firstAffected = Infinity
  for (const [page, items] of pages) {
    if (items.some(matchId)) {
      if (page < firstAffected) firstAffected = page
    }
  }
  mutationSeq++
  if (firstAffected === Infinity) {
    // 已加载页没有命中（如跨列表场景）：轻量全量重置，由渲染循环重新拉取
    inflight.clear()
    if (typeof totalHint === 'number') emit('total-update', totalHint)
    version.value++
    return
  }
  const sorted = [...pages.keys()].sort((a, b) => a - b)
  const affected = sorted.filter(p => p >= firstAffected)
  let deficit = 0   // 当前页需要从后续页补位的项数
  for (let i = 0; i < affected.length; i++) {
    const page = affected[i]
    const items = pages.get(page) || []
    const kept = items.filter(it => !matchId(it))
    if (deficit > 0) {
      const take = Math.min(deficit, kept.length)
      if (take > 0) {
        const prev = pages.get(page - 1)
        if (prev) {
          for (let t = 0; t < take; t++) prev.push(kept.shift())
          deficit -= take
        }
      }
    }
    deficit += (items.length - kept.length)   // 本页被删项数
    pages.set(page, kept)
    // 补位链断裂（下一页不在缓存中）且仍有缺口：从本页起之后全部失效，滚动时重拉
    if (deficit > 0 && !pages.has(page + 1) && i < affected.length - 1) {
      for (const p of affected.slice(i)) pages.delete(p)
      deficit = 0
      break
    }
  }
  // 链尾仍有缺口（后续数据未加载）：保留该页现有数据渲染（删除瞬间不闪烁），
  // 强制重拉补齐尾部缺口（响应返回后自动替换为前移后的完整数据）
  if (deficit > 0) {
    const lastAffected = affected[affected.length - 1]
    fetchAndCache(lastAffected, true)
  }
  inflight.clear()
  if (typeof totalHint === 'number') emit('total-update', totalHint)
  version.value++
}

// 整体清空（如清空回收站）
function clearAll(totalHint) {
  mutationSeq++
  pages.clear()
  inflight.clear()
  if (typeof totalHint === 'number') emit('total-update', totalHint)
  version.value++
}

const visibleCells = computed(() => {
  version.value // 响应式依赖：页加载后重算
  const c = cols.value
  if (c <= 0 || props.rowHeight <= 0) return []
  const firstRow = Math.max(0, Math.floor(scrollTop.value / props.rowHeight) - props.bufferRows)
  const lastRow = Math.min(rows.value - 1, Math.ceil((scrollTop.value + viewportH.value) / props.rowHeight) + props.bufferRows)
  const cells = []
  for (let r = firstRow; r <= lastRow; r++) {
    const base = r * c
    for (let col = 0; col < c; col++) {
      const index = base + col
      if (index >= props.total) break
      const page = pageOf(index)
      fetchAndCache(page)
      const list = pages.get(page)
      const offset = index - page * props.pageSize
      const item = list ? list[offset] : null
      // 容错与自愈：若当前页已返回但列表长度不足以覆盖 offset（曾发生删除且后续页未补位），立即强制重新拉取本页
      if (list && item === undefined && !inflight.has(page)) {
        fetchAndCache(page, true)
      }
      cells.push({ index, row: r, col, item: item || null })
    }
  }
  // 释放远离可视区的页（内存有界）
  const keepMin = pageOf(firstRow * c) - 2
  const keepMax = pageOf(lastRow * c + c - 1) + 2
  for (const k of [...pages.keys()]) {
    if (k < keepMin || k > keepMax) pages.delete(k)
  }
  if (pages.size > props.maxCachedPages) {
    const sorted = [...pages.keys()].sort((a, b) => a - b)
    const drop = sorted.length - props.maxCachedPages
    for (let i = 0; i < drop; i++) {
      const k = sorted[i]
      if (k < keepMin || k > keepMax) pages.delete(k)
    }
  }
  return cells
})

function cellStyle(cell) {
  const pad = props.grid ? 5 : 0   // 网格模式在 cell 内留边距：卡片之间有间隙，支持从中间拉框多选
  return {
    position: 'absolute',
    top: cell.row * props.rowHeight + 'px',
    left: cell.col * props.colWidth + 'px',
    // 表格模式（grid=false）：行宽 = 视口宽，列由内部 flex 布局分配
    width: (props.grid ? props.colWidth : viewportW.value) + 'px',
    height: props.rowHeight + 'px',
    padding: pad + 'px',
    boxSizing: 'border-box',
  }
}

function onScroll() {
  if (!viewportEl.value) return
  scrollTop.value = viewportEl.value.scrollTop
  viewportH.value = viewportEl.value.clientHeight
}

function reset() {
  mutationSeq++
  pages.clear()
  inflight.clear()
  scrollTop.value = 0
  if (viewportEl.value) viewportEl.value.scrollTop = 0
  version.value++
  fetchAndCache(0, true)
}
// 轻量重渲染：数据不变但强制重算可视单元格
function bump() {
  version.value++
}
// 就地替换某个条目对象（按引用查找）：替换后 version++ 触发重渲染，
// slot 中 :item 引用变化 → 子组件（FileCard）props 变化才会重新渲染
function patchItemByRef(target, patch) {
  for (const list of pages.values()) {
    const i = list.findIndex(it => it === target)
    if (i >= 0) {
      list[i] = { ...list[i], ...patch }
      version.value++
      return true
    }
  }
  return false
}

function patchItemById(id, patch) {
  for (const list of pages.values()) {
    const i = list.findIndex(it => it && (it.id === id || it.fav_id === id))
    if (i >= 0) {
      list[i] = { ...list[i], ...patch }
      version.value++
      return list[i]
    }
  }
  return null
}
function getScrollTop() {
  return viewportEl.value ? viewportEl.value.scrollTop : 0
}
// 程序化定位：同步内部状态（scroll 事件不会因赋值触发），立即重算渲染区间并加载缺失页
function scrollTo(y) {
  if (!viewportEl.value) return
  viewportEl.value.scrollTop = y
  scrollTop.value = y
  viewportH.value = viewportEl.value.clientHeight
  version.value++
}

// 确保指定绝对索引项处于当前可视区域内（上下方向键滚动对齐）
function ensureIndexVisible(index) {
  if (!viewportEl.value || index < 0 || index >= props.total) return
  const c = cols.value
  if (c <= 0 || props.rowHeight <= 0) return
  const row = Math.floor(index / c)
  const itemTop = row * props.rowHeight
  const itemBottom = itemTop + props.rowHeight
  const viewTop = scrollTop.value
  const viewH = viewportH.value || viewportEl.value.clientHeight || 500
  const viewBottom = viewTop + viewH

  const pad = 12 // 留适当边距
  if (itemTop < viewTop + pad) {
    scrollTo(Math.max(0, itemTop - pad))
  } else if (itemBottom > viewBottom - pad) {
    scrollTo(itemBottom - viewH + pad)
  }
}

// 根据绝对索引获取条目数据对象（若所在页尚未加载则触发拉取）
function getItemByIndex(index) {
  if (index < 0 || index >= props.total) return null
  const page = pageOf(index)
  fetchAndCache(page)
  const list = pages.get(page)
  return list ? list[index - page * props.pageSize] : null
}

// 根据 ID 或 fav_id 查找条目在全局数据中的绝对索引
function findIndexById(id) {
  if (!id) return -1
  for (const [page, list] of pages.entries()) {
    if (!list) continue
    const offset = list.findIndex(it => it && (it.id === id || it.fav_id === id))
    if (offset >= 0) return page * props.pageSize + offset
  }
  return -1
}

// 刷新当前视口所覆盖的所有页（在后台删除任务完成等时机调用，彻底抹平空洞）
function refreshVisible() {
  const c = cols.value
  if (c <= 0 || props.rowHeight <= 0 || props.total <= 0) return
  const firstRow = Math.max(0, Math.floor(scrollTop.value / props.rowHeight) - props.bufferRows)
  const lastRow = Math.min(rows.value - 1, Math.ceil((scrollTop.value + viewportH.value) / props.rowHeight) + props.bufferRows)
  const pMin = pageOf(firstRow * c)
  const pMax = pageOf(Math.min(props.total - 1, lastRow * c + c - 1))
  for (let p = Math.max(0, pMin); p <= Math.max(0, pMax); p++) {
    fetchAndCache(p, true)
  }
}

let ro = null

/* ---------- Shift / Alt+Shift 滚轮快速纵向滚动 ---------- */
function onWheel(e) {
  if (!e.shiftKey) return
  // 阻止浏览器原生把 Shift+滚轮 转为水平滚动的默认行为
  e.preventDefault()

  // 跨设备与浏览器兼容提取步长：优先取垂直分量，若为 0 则取水平转换分量
  let rawDelta = 0
  if (Math.abs(e.deltaY) > 0) rawDelta = e.deltaY
  else if (Math.abs(e.deltaX) > 0) rawDelta = e.deltaX
  if (!rawDelta) return

  let baseDelta = rawDelta
  // 规范化不同设备的 deltaMode (0: 像素, 1: 行, 2: 页)
  if (e.deltaMode === 1) baseDelta *= 30
  else if (e.deltaMode === 2) baseDelta *= (viewportH.value || 600)

  // 速度倍率：
  // - Shift + 滚轮：4 倍速快速滚动（均匀连贯扫视）
  // - Alt + Shift + 滚轮：12 倍速极速滚动
  const multiplier = e.altKey ? 12 : 4
  const step = baseDelta * multiplier

  if (viewportEl.value) {
    viewportEl.value.scrollTop += step
    scrollTop.value = viewportEl.value.scrollTop
  }
}

onMounted(() => {
  if (viewportEl.value) {
    viewportEl.value.addEventListener('wheel', onWheel, { passive: false })
  }
  ro = new ResizeObserver(() => {
    if (!viewportEl.value) return
    viewportH.value = viewportEl.value.clientHeight
    viewportW.value = viewportEl.value.clientWidth
    version.value++
  })
  ro.observe(viewportEl.value)
  viewportH.value = viewportEl.value.clientHeight
  viewportW.value = viewportEl.value.clientWidth
  // total=0 时没有任何可见单元格，必须主动拉取第 0 页，否则首屏永远空白
  fetchAndCache(0)
})
onBeforeUnmount(() => {
  if (viewportEl.value) {
    viewportEl.value.removeEventListener('wheel', onWheel)
  }
  ro && ro.disconnect()
})

watch(() => props.total, () => { version.value++ })
function getCells() {
  return [...cellRefs.values()].filter(c => c.el && c.item)
}
defineExpose({
  reset,
  bump,
  patchItemByRef,
  patchItemById,
  pages,
  cols,
  scrollTo,
  getScrollTop,
  getCells,
  removeAndRefresh,
  clearAll,
  ensureIndexVisible,
  getItemByIndex,
  findIndexById,
  refreshVisible,
  ensurePagesLoaded,
  pageSize: computed(() => props.pageSize),
})
</script>

<style scoped>
.vl-viewport {
  position: absolute;
  inset: 0;
  overflow-y: auto;
  overflow-x: hidden;
  will-change: scroll-position;
}
.vl-canvas {
  position: relative;
  width: 100%;
}
</style>
