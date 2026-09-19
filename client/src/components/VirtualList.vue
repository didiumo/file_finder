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

const cols = computed(() => (props.grid ? Math.max(1, Math.floor(viewportW.value / props.colWidth)) : 1))
const rows = computed(() => Math.ceil(Math.max(0, props.total) / cols.value))
const canvasHeight = computed(() => rows.value * props.rowHeight)

const pageOf = idx => Math.floor(idx / props.pageSize)

function fetchAndCache(page) {
  if (pages.has(page) || inflight.has(page)) return
  const p = Promise.resolve(props.fetchPage(page))
    .then(res => {
      pages.set(page, res?.items || [])
      if (typeof res?.total === 'number') emit('total-update', res.total)
      return res
    })
    .catch(() => { pages.set(page, []) })
    .finally(() => {
      inflight.delete(page)
      version.value++
    })
  inflight.set(page, p)
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
      cells.push({ index, row: r, col, item: list ? list[index - page * props.pageSize] : null })
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
  return {
    position: 'absolute',
    top: cell.row * props.rowHeight + 'px',
    left: cell.col * props.colWidth + 'px',
    // 表格模式（grid=false）：行宽 = 视口宽，列由内部 flex 布局分配
    width: (props.grid ? props.colWidth : viewportW.value) + 'px',
    height: props.rowHeight + 'px',
  }
}

function onScroll() {
  if (onScroll.raf) return
  onScroll.raf = requestAnimationFrame(() => {
    onScroll.raf = 0
    if (viewportEl.value) {
      scrollTop.value = viewportEl.value.scrollTop
      viewportH.value = viewportEl.value.clientHeight
    }
  })
}

function reset() {
  pages.clear()
  inflight.clear()
  version.value++
}

let ro = null
onMounted(() => {
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
onBeforeUnmount(() => { ro && ro.disconnect() })

watch(() => props.total, () => { version.value++ })
defineExpose({ reset, pages, scrollTo: (y) => { if (viewportEl.value) viewportEl.value.scrollTop = y } })
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
