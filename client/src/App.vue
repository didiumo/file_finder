<!-- App 主布局：TopBar + 虚拟列表 + 侧边预览 + 任务栏 + 弹窗 -->
<template>
  <div class="app" @keydown.esc="onEsc">
    <TopBar
      @filter-change="onFilterChange"
      @refresh="onFilterChange"
      @open-roots="showRoots = true"
    />

    <!-- 文件系统浏览：面包屑（类资源管理器） -->
    <div class="rootstrip" v-if="store.tab === 'fs' && store.fsRoot">
      <span class="rs-label">浏览</span>
      <span class="crumb" :class="{ root: true }" :title="store.fsRoot.path" @click="gotoBreadcrumb(0)">
        {{ store.fsRoot.display_name || store.fsRoot.path }}
      </span>
      <template v-for="(seg, i) in fsSegs" :key="i">
        <span class="rs-sep">/</span>
        <span class="crumb" :title="store.fsRel" @click="gotoBreadcrumb(i + 1)">{{ seg }}</span>
      </template>
      <span class="st-spacer"></span>
      <button class="rs-btn" :disabled="!store.fsRel" @click="goUp">↑ 上级</button>
      <button class="rs-btn accent" @click="enterSearchInDir" title="以当前文件夹为范围进入搜索界面">
        <Icon name="search" :size="12" /> 在此目录搜索
      </button>
    </div>

    <!-- 当前扫描根信息条（搜索/收藏视图） -->
    <div class="rootstrip" v-else-if="store.tab !== 'fs' && currentRoot">
      <span class="rs-label">扫描根</span>
      <span class="rs-path" :title="currentRoot.path">{{ currentRoot.path }}</span>
      <span class="rs-sep">·</span>
      <span class="rs-stat">{{ formatCount(currentRoot.file_count) }} 文件 / {{ formatCount(currentRoot.dir_count) }} 目录</span>
      <span class="rs-sep">·</span>
      <span v-if="currentRoot.last_scan_at" class="rs-stat">上次扫描 {{ formatDate(currentRoot.last_scan_at) }}</span>
      <span v-else class="rs-stat rs-never">未扫描</span>
      <span v-if="currentRoot.last_scan_status === 'running'" class="rs-running">扫描中…</span>
      <span v-else-if="currentRoot.last_scan_status === 'failed'" class="rs-bad">上次扫描失败</span>
      <span v-if="currentRoot.enabled === false" class="rs-bad">已停用</span>
      <span v-if="store.searchScope" class="scope-tip">
        搜索范围：{{ store.searchScope.label }}
        <button class="scope-clear" @click="clearScope">✕</button>
      </span>
    </div>
    <div class="rootstrip" v-else-if="store.roots && store.roots.length">
      <span class="rs-label">扫描根</span>
      <span class="rs-path muted">全部根目录（{{ store.roots.length }} 个），当前显示默认根</span>
      <button class="rs-btn" @click="showRoots = true">查看/管理</button>
    </div>

    <div class="main">
      <div class="list-area">
        <!-- 表格表头：列标题 + 排序 + 可拖拽列宽 -->
        <div v-if="isTable" class="tbl-head">
          <div class="th th-ic"></div>
          <div v-for="col in tableColsDef" :key="col.key" class="th"
               :class="{ sortable: colSortable(col.key), on: store.sort === col.key }"
               :style="colStyle(col)"
               :title="colSortable(col.key) ? '点击排序' : ''"
               @click="colSortable(col.key) && onSortHead(col.key)">
            <span class="th-label">{{ col.label }}</span>
            <span v-if="store.sort === col.key" class="th-arrow">{{ store.order === 'asc' ? '↑' : '↓' }}</span>
            <span v-if="!col.flex" class="th-res" @mousedown.stop="startColDrag(col.key, $event)"></span>
          </div>
          <div class="th th-fav"></div>
        </div>
        <VirtualList
          ref="listRef"
          :key="listKey"
          :head-height="isTable ? 31 : 0"
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
            <!-- 表格视图（列宽与表头一致，可随表头拖拽调整） -->
            <div v-if="isTable" class="trow" :class="{ sel: selectedId(item) }"
                 @click="onCellClick(item)" @dblclick="onCellDbl(item)">
              <span class="t-ic" :style="{ color: item && itemColor(item), width: 26 }">
                <Icon v-if="item" :name="iconOf(item)" :size="15" />
              </span>
              <span class="t-name" :style="colStyle({ key: 'name' })"
                    :title="item ? (item.rel_path || item.name) : ''">{{ item ? item.name : '' }}</span>
              <span class="t-ext" :style="colStyle({ key: 'ext' })">{{ item ? (item.ext || (item.is_dir ? '目录' : '—')) : '' }}</span>
              <span class="t-size" :style="colStyle({ key: 'size' })">{{ item ? formatSize(item.size) : '' }}</span>
              <span class="t-date" :style="colStyle({ key: 'mtime' })">{{ item ? formatDate(item.mtime) : '' }}</span>
              <span class="t-path" style="flex:1 1 0; min-width:80px" :title="item && item.root_path">{{ item ? item.root_path : '' }}</span>
              <span class="t-fav" :style="{ width: 24 }">
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
              @dbl="onCellDbl"
            />
          </template>
        </VirtualList>

        <!-- 空状态 -->
        <div v-if="activeTotal === 0 && !initialLoading" class="empty-tip">
          <Icon name="search" :size="40" />
          <p>{{ emptyText }}</p>
          <p class="sub">{{ emptySub }}</p>
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
          <button v-if="store.tab === 'fs'" class="st-btn accent" @click="enterSearchInDir">
            <Icon name="search" :size="13" /> 在此目录搜索
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
import { store, viewCfg, tableCols, saveTableCols } from './store'
import { trackTask } from './tasks'
import { apiSearch, apiFavorites, apiRoots, apiStats, apiFiles, apiFs } from './api'
import { formatSize, formatDate } from './utils/format'
import { fileIcon, fileColor } from './utils/fileTypes'

const pageSize = 300
const listRef = ref(null)

/* ---------- 表格视图：列定义 / 排序 / 列宽拖拽 ---------- */
const tableColsDef = [
  { key: 'name', label: '名称' },
  { key: 'ext', label: '类型' },
  { key: 'size', label: '大小' },
  { key: 'mtime', label: '修改时间' },
  { key: 'path', label: '路径', flex: true },
]
const colKey = (k) => (k === 'mtime' ? 'date' : k)
const COL_MIN = { name: 140, ext: 50, size: 70, date: 110 }
function colStyle(col) {
  if (col.flex) return { flex: '1 1 0', minWidth: '80px' }
  const key = colKey(col.key)
  return { flex: `0 1 ${tableCols[key]}px`, minWidth: (COL_MIN[key] || 60) + 'px' }
}
function colSortable(key) {
  if (store.tab === 'fs') return ['name', 'size', 'mtime'].includes(key)
  if (store.tab === 'favorites') return ['name', 'size', 'mtime'].includes(key)
  return ['name', 'ext', 'size', 'mtime', 'path'].includes(key)
}
function onSortHead(key) {
  if (!colSortable(key)) return
  if (store.sort === key) store.order = store.order === 'asc' ? 'desc' : 'asc'
  else { store.sort = key; store.order = 'asc' }
  onFilterChange()
}
let dragCol = null
let dragStartX = 0
let dragStartW = 0
function startColDrag(key, e) {
  dragCol = key
  dragStartX = e.clientX
  dragStartW = tableCols[colKey(key)]
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onColDrag)
  window.addEventListener('mouseup', stopColDrag)
  e.preventDefault()
}
function onColDrag(e) {
  if (!dragCol) return
  tableCols[colKey(dragCol)] = Math.max(60, Math.min(900, dragStartW + (e.clientX - dragStartX)))
}
function stopColDrag() {
  dragCol = null
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', onColDrag)
  window.removeEventListener('mouseup', stopColDrag)
  saveTableCols()
}
const taskBarRef = ref(null)
const showRoots = ref(false)
const showCollect = ref(false)
const listKey = ref(0)
const initialLoading = ref(true)
const loadedPages = ref(0)
const pageCursors = [null]   // pageCursors[n] = 第 n 页的入参游标（来自 n-1 页响应的 next_cursor）
const fsCursors = [null]     // 文件系统浏览的游标（与 pageCursors 隔离）

const cfg = computed(() => viewCfg())
const isTable = computed(() => store.viewMode === 'table')
const activeTotal = computed(() => {
  if (store.tab === 'favorites') return store.favTotal
  if (store.tab === 'fs') return store.fsTotal
  return store.searchTotal
})
const loadedCount = computed(() => Math.min(loadedPages.value * pageSize, activeTotal.value))
const currentRoot = computed(() => {
  const rs = store.roots || []
  if (store.rootId) return rs.find(r => r.id === store.rootId) || null
  return rs[0] || null
})
const fsSegs = computed(() => (store.fsRel ? store.fsRel.split('/') : []))
const emptyText = computed(() => {
  if (store.tab === 'favorites') return '暂无收藏内容'
  if (store.tab === 'fs') return '目录为空'
  return '没有匹配的文件'
})
const emptySub = computed(() => {
  if (store.tab === 'fs') return '可点击「↑ 上级」返回，或在「设置」中添加扫描根目录'
  return '可尝试调整搜索词 / 过滤条件，或在「设置」中添加扫描根目录'
})

function formatCount(n) {
  n = n || 0
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万'
  return n.toLocaleString()
}

/* ---------- 文件系统路径工具 ---------- */

function fsAbsPath() {
  if (!store.fsRoot) return ''
  if (!store.fsRel) return store.fsRoot.path
  return store.fsRoot.path + '\\' + store.fsRel.split('/').join('\\')
}

/* ---------- 数据装配 ---------- */

function searchParams(page, cursor) {
  const scope = store.searchScope || {}
  const p = {
    q: store.q,
    root_id: scope.root_id != null ? scope.root_id : store.rootId,
    prefix: scope.prefix || null,
    regex: store.regex ? 1 : null,
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
  const gen = listKey.value   // 本次请求所属列表代次（重建后旧响应必须丢弃）
  loadedPages.value = Math.max(loadedPages.value, pageIdx + 1)
  if (store.tab === 'favorites') {
    const p = {
      q: store.q, root_id: store.rootId, sort: store.sort === 'name' ? 'name' : store.sort,
      order: store.order, ext: store.ext,
      page: pageIdx + 1, page_size: pageSize,
    }
    for (const k of Object.keys(p)) if (p[k] === null || p[k] === undefined || p[k] === '') delete p[k]
    const r = await apiFavorites.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.favTotal = r.data.total
    // 收藏项映射 file_id → id（缩略图/预览用），缺失文件 id 为 null
    const items = r.data.items.map(f => ({
      ...f,
      id: f.file_id || null,
      favorite: true,
    }))
    return { total: r.data.total, items }
  }
  if (store.tab === 'fs') {
    if (!store.fsRoot) return { total: 0, items: [] }
    const cursor = fsCursors[pageIdx] || null
    const p = {
      path: fsAbsPath(),
      page: pageIdx + 1,
      page_size: pageSize,
      sort: store.sort,
      order: store.order,
      ...(cursor || {}),
    }
    const r = await apiFs.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.fsTotal = r.data.total
    fsCursors[pageIdx + 1] = r.data.next_cursor || null
    return { total: r.data.total, items: r.data.items }
  }
  // 游标分页：顺序滚动时深翻页不重扫 OFFSET
  const cursor = pageCursors[pageIdx] || null
  const r = await apiSearch(searchParams(pageIdx + 1, cursor))
  if (gen !== listKey.value) return { total: 0, items: [] }
  store.searchTotal = r.data.total
  pageCursors[pageIdx + 1] = r.data.next_cursor || null
  return { total: r.data.total, items: r.data.items }
}

function onTotalUpdate(total) {
  if (store.tab === 'favorites') store.favTotal = total
  else if (store.tab === 'fs') store.fsTotal = total
  else store.searchTotal = total
}

function onFilterChange() {
  // 进入文件系统 Tab 但尚无浏览根时，默认第一个扫描根
  if (store.tab === 'fs' && !store.fsRoot && store.roots.length) {
    store.fsRoot = store.roots[0]
    store.fsRel = ''
  }
  loadedPages.value = 0
  pageCursors.length = 0
  pageCursors[0] = null
  fsCursors.length = 0
  fsCursors[0] = null
  listKey.value++          // 重建 VirtualList（清空页缓存）
  store.selected = null
  store.previewKey++
  refreshStats()
}

function clearScope() {
  store.searchScope = null
  onFilterChange()
}

/* ---------- 文件系统浏览交互 ---------- */

function enterDir(item) {
  store.fsRel = item.rel_path
  store.selected = null
  store.previewKey++
  onFilterChange()
}

function gotoBreadcrumb(idx) {
  const segs = store.fsRel ? store.fsRel.split('/') : []
  store.fsRel = segs.slice(0, idx).join('/')
  store.selected = null
  store.previewKey++
  onFilterChange()
}

function goUp() {
  if (!store.fsRel) return
  const segs = store.fsRel.split('/')
  segs.pop()
  store.fsRel = segs.join('/')
  store.selected = null
  store.previewKey++
  onFilterChange()
}

function openFsDir(item) {
  const root = store.roots.find(r => r.id === item.root_id)
  if (!root) return
  store.fsRoot = root
  store.fsRel = item.rel_path
  store.tab = 'fs'
  store.selected = null
  store.previewKey++
  onFilterChange()
}

function enterSearchInDir() {
  if (!store.fsRoot) return
  const label = store.fsRoot.display_name || store.fsRoot.path
  store.searchScope = {
    root_id: store.fsRoot.id,
    prefix: store.fsRel || '',
    label: label + (store.fsRel ? '/' + store.fsRel : ''),
  }
  store.q = ''
  store.tab = 'search'
  store.selected = null
  store.previewKey++
  onFilterChange()
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
  if (!item) return
  if (item.is_dir) {
    if (store.tab === 'fs') enterDir(item)
    else openFsDir(item)
    return
  }
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
    const rs = roots?.data
    store.roots = Array.isArray(rs) ? rs : (rs?.roots || [])
    store.stats = stats?.data
    // 默认选中第一个扫描根（用户只关心指定目录），信息条即显示完整路径
    if (store.rootId == null && store.roots.length) {
      store.rootId = store.roots[0].id
    }
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

/* 扫描根信息条 / 面包屑 */
.rootstrip {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 12px; background: #17191c;
  border-bottom: 1px solid #2e3137;
  font-size: 11.5px; color: #8b919a;
  flex-wrap: wrap;
}
.rs-label {
  color: #5f6474; font-weight: 600;
  background: #26282d; border-radius: 4px; padding: 1px 7px;
}
.rs-path {
  font-family: Consolas, monospace; color: #aab0b8;
  max-width: 620px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rs-path.muted { color: #6c727c; font-family: inherit; }
.rs-sep { color: #3a3d44; }
.rs-stat { color: #8b919a; }
.rs-never { color: #d9a53f; }
.rs-running { color: #6ab0ff; }
.rs-bad { color: #e05c5c; }
.rs-btn {
  background: #26282d; border: 1px solid #33363d; color: #9aa0a6;
  border-radius: 5px; padding: 1px 8px; font-size: 11px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
}
.rs-btn:hover:not(:disabled) { color: #e3e6eb; }
.rs-btn:disabled { opacity: .4; cursor: default; }
.rs-btn.accent { color: #6ab0ff; border-color: #3d556e; }
.rs-btn.accent:hover { background: rgba(76,139,245,.12); }
.crumb {
  color: #aab0b8; cursor: pointer; padding: 1px 6px; border-radius: 4px;
  font-family: Consolas, monospace; max-width: 260px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.crumb:hover { background: rgba(255,255,255,.07); color: #fff; }
.crumb.root { color: #6ab0ff; }
.scope-tip {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(76,139,245,.12); border: 1px solid #3d556e; color: #6ab0ff;
  border-radius: 5px; padding: 0 7px; font-size: 11px;
}
.scope-clear {
  background: none; border: none; color: inherit; cursor: pointer;
  padding: 0 2px; font-size: 10px; opacity: .7;
}
.scope-clear:hover { opacity: 1; }
.st-spacer { flex: 1; }

/* 表格表头 */
.tbl-head {
  position: absolute; top: 0; left: 0; right: 0; height: 31px;
  display: flex; align-items: center; gap: 8px; padding: 0 10px;
  background: #1a1c1f; border-bottom: 1px solid #2e3137;
  font-size: 11.5px; color: #8b919a; user-select: none; z-index: 6;
}
.th { display: flex; align-items: center; gap: 4px; height: 100%; position: relative; flex: 0 0 auto; }
.th-ic { width: 26px; flex: 0 0 26px; }
.th-fav { width: 24px; flex: 0 0 24px; }
.th.sortable { cursor: pointer; }
.th.sortable:hover { color: #e3e6eb; }
.th.on { color: #6ab0ff; }
.th-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.th-arrow { font-size: 11px; }
.th-res {
  position: absolute; right: -5px; top: 0; bottom: 0; width: 10px;
  cursor: col-resize; z-index: 2;
}
.th-res:hover { background: rgba(76,139,245,.35); }

/* 表格行（列宽与表头一致） */
.trow {
  display: flex; align-items: center; gap: 8px;
  height: 100%; padding: 0 10px;
  border-bottom: 1px solid rgba(255,255,255,.03);
  font-size: 12.5px; color: #c9cdd4; cursor: default;
  white-space: nowrap; overflow: hidden;
}
.trow:hover { background: rgba(255,255,255,.04); }
.trow.sel { background: rgba(76,139,245,.16); }
.t-ic { width: 26px; flex: 0 0 26px; display: flex; }
.t-name { flex: 0 0 auto; overflow: hidden; text-overflow: ellipsis; color: #e3e6eb; }
.t-ext { flex: 0 0 auto; color: #8b919a; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; }
.t-size { flex: 0 0 auto; color: #8b919a; text-align: right; }
.t-date { flex: 0 0 auto; color: #8b919a; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; }
.t-path { flex: 1 1 0; color: #6c727c; font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; }
.t-fav { width: 24px; flex: 0 0 24px; display: flex; }
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
