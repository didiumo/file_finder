<!-- App 主布局：TopBar + 虚拟列表 + 侧边预览 + 任务栏 + 弹窗 -->
<template>
  <div class="app" @keydown.esc="onEsc">
    <TopBar
      @filter-change="onFilterChange"
      @refresh="onFilterChange"
      @open-roots="showRoots = true"
    />

    <div class="main">
      <div class="list-area">
        <VirtualList
          ref="listRef"
          :key="listKey"
          :total="activeTotal"
          :page-size="pageSize"
          :fetch-page="fetchPage"
          :grid="store.viewMode !== 'table'"
          :col-width="cfg.colWidth"
          :row-height="isTable ? 36 : cfg.rowHeight"
          :buffer-rows="8"
          @total-update="onTotalUpdate"
        >
          <template #item="{ item, index }">
            <!-- 表格视图 -->
            <div v-if="isTable" class="trow" :class="{ sel: selectedId(item) }"
                 @click="onCellClick(item)" @dblclick="onCellDbl(item)">
              <span class="t-ic" :style="{ color: item && itemColor(item) }">
                <Icon v-if="item" :name="iconOf(item)" :size="15" />
              </span>
              <span class="t-name" :title="item && item.rel_path">{{ item ? item.name : '' }}</span>
              <span class="t-ext">{{ item ? (item.ext || '—') : '' }}</span>
              <span class="t-size">{{ item ? formatSize(item.size) : '' }}</span>
              <span class="t-date">{{ item ? formatDate(item.mtime) : '' }}</span>
              <span class="t-path" :title="item && item.root_path">{{ item ? item.root_path : '' }}</span>
              <span class="t-fav">
                <Icon v-if="item && (item.favorite || item.fav_id)" name="star" :size="13" style="color:#f5b942" />
              </span>
              <span v-if="item && item.exists_now === false" class="t-miss">丢失</span>
            </div>
            <!-- 卡片视图 -->
            <FileCard
              v-else
              :item="item"
              :mode="store.viewMode"
              :selected="selectedId(item)"
              @select="onCellClick"
              @fav="onToggleFav"
            />
          </template>
        </VirtualList>

        <!-- 空状态 -->
        <div v-if="activeTotal === 0 && !initialLoading" class="empty-tip">
          <Icon name="search" :size="40" />
          <p>{{ store.tab === 'favorites' ? '暂无收藏内容' : '没有匹配的文件' }}</p>
          <p class="sub">可尝试调整搜索词 / 过滤条件，或在「设置」中添加扫描根目录</p>
        </div>

        <!-- 状态栏 -->
        <div class="statusbar">
          <span class="st-item">共 <b>{{ activeTotal.toLocaleString() }}</b> 项</span>
          <span class="st-item">已加载 <b>{{ loadedCount }}</b> 项</span>
          <span v-if="store.selected" class="st-item sel-info">
            <Icon name="eye" :size="12" /> {{ store.selected.name }}
          </span>
          <span class="st-spacer"></span>
          <button class="st-btn" :class="{ on: store.showPreview }" @click="store.showPreview = !store.showPreview">
            <Icon name="eye" :size="13" /> 预览
          </button>
          <button v-if="store.tab === 'favorites'" class="st-btn" @click="pruneMissing">
            <Icon name="trash" :size="13" /> 清除失效收藏
          </button>
          <button class="st-btn accent" @click="showCollect = true">
            <Icon name="package" :size="13" /> 整理收藏
          </button>
        </div>
      </div>

      <PreviewPanel v-if="store.showPreview" @deleted="onFilterChange" />
    </div>

    <TaskBar ref="taskBarRef" />

    <RootManager :open="showRoots" @close="showRoots = false" @task="trackTask" />
    <CollectDialog :open="showCollect" @close="showCollect = false" @task="trackTask" @done="onFilterChange" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import TopBar from './components/TopBar.vue'
import VirtualList from './components/VirtualList.vue'
import FileCard from './components/FileCard.vue'
import PreviewPanel from './components/PreviewPanel.vue'
import TaskBar from './components/TaskBar.vue'
import RootManager from './components/RootManager.vue'
import CollectDialog from './components/CollectDialog.vue'
import Icon from './components/Icon.vue'
import { store, viewCfg } from './store'
import { trackTask } from './tasks'
import { apiSearch, apiFavorites, apiRoots, apiStats, apiFiles } from './api'
import { formatSize, formatDate } from './utils/format'
import { fileIcon, fileColor } from './utils/fileTypes'

const pageSize = 300
const listRef = ref(null)
const taskBarRef = ref(null)
const showRoots = ref(false)
const showCollect = ref(false)
const listKey = ref(0)
const initialLoading = ref(true)
const loadedPages = ref(0)
const pageCursors = [null]   // pageCursors[n] = 第 n 页的入参游标（来自 n-1 页响应的 next_cursor）

const cfg = computed(() => viewCfg())
const isTable = computed(() => store.viewMode === 'table')
const activeTotal = computed(() => (store.tab === 'favorites' ? store.favTotal : store.searchTotal))
const loadedCount = computed(() => loadedPages.value * pageSize)

/* ---------- 数据装配 ---------- */

function searchParams(page, cursor) {
  const p = {
    q: store.q,
    root_id: store.rootId,
    ext: store.ext,
    fav_only: store.favOnly ? 1 : null,
    sort: store.sort,
    order: store.order,
    page,
    page_size: pageSize,
    ...(cursor || {}),
  }
  // 空参数直接去掉，避免服务端误判
  for (const k of Object.keys(p)) if (p[k] === null || p[k] === undefined || p[k] === '') delete p[k]
  return p
}

async function fetchPage(pageIdx) {
  loadedPages.value = Math.max(loadedPages.value, pageIdx + 1)
  if (store.tab === 'favorites') {
    const r = await apiFavorites.list({
      q: store.q, root_id: store.rootId, sort: store.sort, order: store.order,
      page: pageIdx + 1, page_size: pageSize,
    })
    store.favTotal = r.data.total
    // 收藏项映射 file_id → id（缩略图/预览用），缺失文件 id 为 null
    const items = r.data.items.map(f => ({
      ...f,
      id: f.file_id || null,
      favorite: true,
    }))
    return { total: r.data.total, items }
  }
  // 游标分页：顺序滚动时深翻页不重扫 OFFSET
  const cursor = pageCursors[pageIdx] || null
  const r = await apiSearch(searchParams(pageIdx + 1, cursor))
  store.searchTotal = r.data.total
  pageCursors[pageIdx + 1] = r.data.next_cursor || null
  return { total: r.data.total, items: r.data.items }
}

function onTotalUpdate(total) {
  if (store.tab === 'favorites') store.favTotal = total
  else store.searchTotal = total
}

function onFilterChange() {
  loadedPages.value = 0
  pageCursors.length = 0
  pageCursors[0] = null
  listKey.value++          // 重建 VirtualList（清空页缓存）
  store.selected = null
  store.previewKey++
  refreshStats()
}

/* ---------- 交互 ---------- */

function selectedId(item) {
  if (!store.selected || !item) return false
  if (store.tab === 'favorites') return store.selected.fav_id === item.fav_id
  return store.selected.id === item.id
}

function onCellClick(item) {
  if (!item) return
  store.selected = item
  store.previewKey++
}
function onCellDbl(item) {
  if (!item || item.is_dir) return
  // 双击下载（模拟 Everything 双击打开）
  const a = document.createElement('a')
  a.href = apiFiles.downloadUrl(item.id)
  a.download = item.name
  a.click()
}

async function onToggleFav(item) {
  if (!item) return
  if (store.tab === 'favorites') {
    if (item.fav_id) {
      await apiFavorites.remove(item.fav_id)
      onFilterChange()
    }
    return
  }
  const r = await apiFavorites.toggle(item.id)
  item.favorite = r.data.favorite
  if (r.data.favorite) store.favTotal++
  else store.favTotal = Math.max(0, store.favTotal - 1)
}

async function pruneMissing() {
  if (!confirm('清除所有磁盘上已不存在的收藏记录？')) return
  await apiFavorites.pruneMissing()
  onFilterChange()
}

/* ---------- 初始化与杂项 ---------- */

async function refreshStats() {
  try {
    const r = await apiStats()
    store.stats = r.data
  } catch { /* noop */ }
}

function onEsc() {
  if (showRoots.value) { showRoots.value = false; return }
  if (showCollect.value) { showCollect.value = false; return }
  store.selected = null
  store.previewKey++
}

async function init() {
  try {
    const [roots, stats] = await Promise.all([apiRoots.list(), apiStats()])
    store.roots = roots.data.roots
    store.stats = stats.data
  } catch (e) {
    console.error('初始化失败', e)
  }
  initialLoading.value = false
}

onMounted(() => {
  init()
  window.addEventListener('keydown', onGlobalKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))

function onGlobalKey(e) {
  if (e.key === 'Escape') onEsc()
}

const iconOf = fileIcon
const itemColor = fileColor
</script>

<style>
html, body, #app {
  margin: 0; height: 100%; overflow: hidden;
  background: #1e1f22; color: #d5d9e0;
  font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
  font-size: 13px;
}
* { box-sizing: border-box; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #3a3d44; border-radius: 5px; border: 2px solid #1e1f22; }
::-webkit-scrollbar-thumb:hover { background: #4a4e57; }
::-webkit-scrollbar-corner { background: transparent; }
</style>

<style scoped>
.app { height: 100vh; display: flex; flex-direction: column; }
.main { flex: 1; display: flex; min-height: 0; }
.list-area { flex: 1; position: relative; min-width: 0; }

/* 表格行 */
.trow {
  display: flex; align-items: center; gap: 8px;
  height: 100%; padding: 0 10px;
  border-bottom: 1px solid rgba(255,255,255,.03);
  font-size: 12.5px; color: #c9cdd4; cursor: default;
  white-space: nowrap; overflow: hidden;
}
.trow:hover { background: rgba(255,255,255,.04); }
.trow.sel { background: rgba(76,139,245,.16); }
.t-ic { width: 20px; display: flex; flex-shrink: 0; }
.t-name { flex: 2.2; overflow: hidden; text-overflow: ellipsis; color: #e3e6eb; }
.t-ext { flex: .6; color: #8b919a; font-size: 11.5px; }
.t-size { flex: .8; color: #8b919a; text-align: right; }
.t-date { flex: 1.1; color: #8b919a; font-size: 11.5px; }
.t-path { flex: 1.8; color: #6c727c; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; }
.t-fav { width: 18px; display: flex; flex-shrink: 0; }
.t-miss { font-size: 10px; color: #fff; background: #e05c5c; border-radius: 4px; padding: 0 5px; line-height: 16px; flex-shrink: 0; }

.empty-tip {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: #5c626d; pointer-events: none;
}
.empty-tip p { margin: 10px 0 0; font-size: 14px; color: #8b919a; }
.empty-tip .sub { font-size: 12px; color: #5c626d; }

/* 状态栏 */
.statusbar {
  position: absolute; left: 0; right: 0; bottom: 0;
  display: flex; align-items: center; gap: 12px;
  padding: 5px 12px; background: #17191c;
  border-top: 1px solid #2e3137; font-size: 11.5px; color: #8b919a;
  z-index: 5;
}
.st-item b { color: #d5d9e0; font-weight: 600; }
.sel-info { display: flex; align-items: center; gap: 4px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-spacer { flex: 1; }
.st-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: #26282d; border: 1px solid #33363d; color: #9aa0a6;
  border-radius: 6px; padding: 3px 9px; font-size: 11.5px; cursor: pointer;
}
.st-btn:hover { color: #e3e6eb; }
.st-btn.on { color: #6ab0ff; border-color: #3d78e6; }
.st-btn.accent { color: #6ab0ff; border-color: #3d556e; }
.st-btn.accent:hover { background: rgba(76,139,245,.12); }
</style>
