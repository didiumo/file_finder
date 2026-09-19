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
      <div class="list-area" @mousedown="onAreaMouseDown">
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
            <div v-if="isTable" class="trow" :class="{ sel: isSel(item) }"
                 @click="onCellClick(item, $event)" @dblclick="onCellDbl(item)"
                 @contextmenu.prevent="onCtx($event, item)">
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
              :selected="isSel(item)"
              @select="(it, e) => onCellClick(it, e)"
              @fav="onToggleFav"
              @dbl="onCellDbl"
              @ctx="onCtx($event, item)"
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
          <span v-if="selCount" class="st-item sel-info accent-info">
            <Icon name="check" :size="12" /> 已选 <b>{{ selCount }}</b> 项
            <button class="st-mini" @click="clearSelection" title="取消全选">✕</button>
          </span>
          <span v-else-if="store.selected" class="st-item sel-info">
            <Icon name="eye" :size="12" /> {{ store.selected.name }}
          </span>
          <span class="st-spacer"></span>
          <template v-if="selCount && store.tab !== 'trash'">
            <button class="st-btn" @click="batchFav" :title="batchFavTitle">
              <Icon name="star" :size="13" /> 收藏
            </button>
            <button class="st-btn danger" @click="batchDelete">
              <Icon name="trash" :size="13" /> 删除
            </button>
          </template>
          <template v-if="selCount && store.tab === 'trash'">
            <button class="st-btn" @click="batchRestore"><Icon name="undo" :size="13" /> 恢复</button>
            <button class="st-btn danger" @click="batchPurge"><Icon name="x" :size="13" /> 彻底删除</button>
          </template>
          <button v-if="store.tab === 'trash'" class="st-btn danger" @click="trashEmpty">
            <Icon name="trash" :size="13" /> 清空回收站
          </button>
          <button v-else class="st-btn" :class="{ on: store.showPreview }" @click="store.showPreview = !store.showPreview">
            <Icon name="eye" :size="13" /> 预览
          </button>
          <button v-if="store.tab === 'favorites'" class="st-btn" @click="pruneMissing">
            <Icon name="trash" :size="13" /> 清除失效收藏
          </button>
          <button v-if="store.tab === 'fs'" class="st-btn accent" @click="enterSearchInDir">
            <Icon name="search" :size="13" /> 在此目录搜索
          </button>
          <button v-if="store.tab !== 'trash'" class="st-btn accent" @click="showCollect = true">
            <Icon name="package" :size="13" /> 整理收藏
          </button>
        </div>
      </div>

      <PreviewPanel v-if="store.showPreview && store.tab !== 'trash'" @deleted="onFilterChange" @enter="onPreviewEnter" />
    </div>

    <TaskBar ref="taskBarRef" />

    <div v-if="ctxMenu" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }" @mousedown.stop @contextmenu.prevent>
      <button v-for="it in ctxMenu.items" :key="it.key" class="ctx-item" :class="{ danger: it.danger }" @click="runCtx(it.key)">
        <Icon :name="it.icon" :size="14" />
        {{ it.label }}
      </button>
    </div>

    <div v-if="confirmBox" class="ff-modal-mask" @mousedown.self="confirmCancel">
      <div class="ff-modal" role="dialog" aria-modal="true">
        <div class="ff-modal-title">{{ confirmBox.title }}</div>
        <div class="ff-modal-msg">{{ confirmBox.message }}</div>
        <div class="ff-modal-actions">
          <button class="st-btn" @click="confirmCancel">取消</button>
          <button class="st-btn danger" @click="confirmOk">{{ confirmBox.danger ? '删除' : '确定' }}</button>
        </div>
      </div>
    </div>

    <RootManager :open="showRoots" @close="showRoots = false" @task="trackTask" />
    <CollectDialog :open="showCollect" @close="showCollect = false" @task="trackTask" @done="onFilterChange" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount , nextTick } from 'vue'
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
import { apiSearch, apiFavorites, apiRoots, apiStats, apiFiles, apiFs, apiTrash } from './api'
import { formatSize, formatDate } from './utils/format'
import { fileIcon, fileColor } from './utils/fileTypes'

const pageSize = 300
const listRef = ref(null)

/* ---------- 多选（Ctrl/Shift + 框选） ---------- */
const selKeys = ref(new Set())   // 已选唯一键集合（跨页累积）
let selAnchor = null             // Shift 范围锚点（唯一键）
const pageItems = {}             // 页索引 -> items（范围选择的有序来源）

function selKeyOf(item) {
  if (!item) return null
  if (store.tab === 'favorites') return 'f' + item.fav_id
  if (store.tab === 'trash') return 't' + item.id
  if (store.tab === 'fs') return 'p' + item.root_id + '/' + item.rel_path
  return 'i' + item.id
}
function isSel(item) {
  const k = selKeyOf(item)
  return !!k && selKeys.value.has(k)
}
const selCount = computed(() => selKeys.value.size)
function clearSelection() {
  selKeys.value = new Set()
  selAnchor = null
}
function orderedItems() {
  const out = []
  for (let i = 0; i < loadedPages.value; i++) out.push(...(pageItems[i] || []))
  return out
}
function selectedItems() {
  const keys = selKeys.value
  return orderedItems().filter(i => keys.has(selKeyOf(i)))
}

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
  if (store.tab === 'trash') return store.trashTotal
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
  if (store.tab === 'trash') return '回收站是空的'
  return '没有匹配的文件'
})
const emptySub = computed(() => {
  if (store.tab === 'fs') return '可点击「↑ 上级」返回，或在「设置」中添加扫描根目录'
  if (store.tab === 'trash') return '删除的文件会先进入回收站，在这里可恢复或彻底删除'
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
  let res
  if (store.tab === 'favorites') {
    const p = {
      q: store.q, root_id: store.rootId, sort: store.sort === 'name' ? 'name' : store.sort,
      order: store.order, ext: store.ext,
      page: pageIdx + 1, page_size: pageSize,
    }
    for (const k of Object.keys(p)) if (p[k] === null || p[k] === undefined || p[k] === '') delete p[k]
    res = await apiFavorites.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.favTotal = res.data.total
    // 收藏项映射 file_id → id（缩略图/预览用），缺失文件 id 为 null
    res.data.items = res.data.items.map(f => ({ ...f, id: f.file_id || null, favorite: true }))
  } else if (store.tab === 'trash') {
    if (store.sort === 'name') store.sort = 'trashed_at'
    // 按删除时间排序时固定降序：最新删除的排最前（刚删的文件立即可见）
    const p = {
      q: store.q, root_id: store.rootId, sort: store.sort,
      order: store.sort === 'trashed_at' ? 'desc' : store.order,
      page: pageIdx + 1, page_size: pageSize,
    }
    for (const k of Object.keys(p)) if (p[k] === null || p[k] === undefined || p[k] === '') delete p[k]
    res = await apiTrash.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.trashTotal = res.data.total
    res.data.items = res.data.items.map(t => ({ ...t, is_dir: !!t.is_dir }))
  } else if (store.tab === 'fs') {
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
    res = await apiFs.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.fsTotal = res.data.total
    fsCursors[pageIdx + 1] = res.data.next_cursor || null
  } else {
    // 游标分页：顺序滚动时深翻页不重扫 OFFSET
    const cursor = pageCursors[pageIdx] || null
    res = await apiSearch(searchParams(pageIdx + 1, cursor))
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.searchTotal = res.data.total
    pageCursors[pageIdx + 1] = res.data.next_cursor || null
  }
  pageItems[pageIdx] = res.data.items || []
  return { total: res.data.total, items: res.data.items || [] }
}

function onTotalUpdate(total) {
  if (store.tab === 'favorites') store.favTotal = total
  else if (store.tab === 'fs') store.fsTotal = total
  else if (store.tab === 'trash') store.trashTotal = total
  else store.searchTotal = total
}

function onFilterChange() {
  // 文件系统 Tab：无浏览根或根已被删除时，重置为第一个扫描根
  if (store.tab === 'fs') {
    const still = store.roots.find(r => r.id === (store.fsRoot && store.fsRoot.id))
    if (!still || !store.fsRoot) {
      store.fsRoot = store.roots[0] || null
      store.fsRel = ''
    }
  }
  loadedPages.value = 0
  pageCursors.length = 0
  pageCursors[0] = null
  fsCursors.length = 0
  fsCursors[0] = null
  listKey.value++          // 重建 VirtualList（清空页缓存）
  store.selected = null
  clearSelection()
  store.previewKey++
  refreshStats()
  // 内容微变（删除/收藏/恢复等）时恢复滚动位置，避免跳回顶部
  if (keepPos) {
    keepPos = false
    const target = preservePos
    nextTick(() => { if (target && listRef.value) listRef.value.scrollTo(target) })
  }
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

function onCellClick(item, e) {
  if (!item) return
  const k = selKeyOf(item)
  const ctrl = e && (e.ctrlKey || e.metaKey)
  const shift = e && e.shiftKey
  if (ctrl) {
    if (selKeys.value.has(k)) {
      const next = new Set(selKeys.value); next.delete(k)
      selKeys.value = next
      if (next.size === 0) selAnchor = null
    } else {
      const next = new Set(selKeys.value); next.add(k)
      selKeys.value = next
      selAnchor = k
    }
  } else if (shift && selAnchor != null) {
    // Shift 语义：每次点击都以锚点为基准重算区间（锚点 → 当前项），替换选区而非追加，
    // 因此连续多次 Shift 点击可任意伸缩（选 10 个后点第 5 个会收缩为前 5 个）
    const ids = orderedItems().map(selKeyOf)
    const a = ids.indexOf(selAnchor)
    const b = ids.indexOf(k)
    if (a >= 0 && b >= 0) {
      const [lo, hi] = a < b ? [a, b] : [b, a]
      const next = new Set()
      for (let i = lo; i <= hi; i++) if (ids[i]) next.add(ids[i])
      selKeys.value = next
    } else {
      // 锚点不在已加载列表（虚拟列表页被释放）时退化为锚点 + 当前项
      const next = new Set([selAnchor, k])
      selKeys.value = next
    }
  } else {
    selKeys.value = new Set([k])
    selAnchor = k
  }
  store.selected = item
  store.previewKey++
}

/* ---------- 拉框多选 ---------- */
let boxStart = null
let boxEl = null
function onAreaMouseDown(e) {
  if (e.button !== 0) return
  const t = e.target
  if (!(t instanceof Element)) return
  // 只在空白区域启动（排除表头/行/卡片/状态栏/控件）
  if (t.closest('.tbl-head, .statusbar, .card, .trow, button, select, input, label, .rootstrip, .ctx-menu, a')) return
  boxStart = { x: e.clientX, y: e.clientY }
  window.addEventListener('mousemove', onBoxMove)
  window.addEventListener('mouseup', onBoxUp)
}
function onBoxMove(e) {
  if (!boxStart) return
  const area = document.querySelector('.list-area')
  if (!area) return
  if (!boxEl) {
    boxEl = document.createElement('div')
    boxEl.className = 'box-select'
    area.appendChild(boxEl)
  }
  const x = Math.min(boxStart.x, e.clientX)
  const y = Math.min(boxStart.y, e.clientY)
  boxEl.style.left = x + 'px'
  boxEl.style.top = y + 'px'
  boxEl.style.width = Math.abs(e.clientX - boxStart.x) + 'px'
  boxEl.style.height = Math.abs(e.clientY - boxStart.y) + 'px'
}
function onBoxUp() {
  window.removeEventListener('mousemove', onBoxMove)
  window.removeEventListener('mouseup', onBoxUp)
  if (!boxStart) return
  boxStart = null
  if (!boxEl) return
  const r = boxEl.getBoundingClientRect()
  boxEl.remove()
  boxEl = null
  if (r.width < 4 && r.height < 4) return  // 视为点击而非框选
  const next = new Set(selKeys.value)
  const cells = listRef.value ? listRef.value.getCells() : []
  for (const { el, item } of cells) {
    const er = el.getBoundingClientRect()
    if (er.left < r.right && er.right > r.left && er.top < r.bottom && er.bottom > r.top) {
      const k = selKeyOf(item)
      if (k) { next.add(k); selAnchor = k }
    }
  }
  selKeys.value = next
}

function downloadItem(item) {
  if (!item || !item.id) return
  const a = document.createElement('a')
  a.href = apiFiles.downloadUrl(item.id)
  a.download = item.name
  a.click()
}
function onCellDbl(item) {
  if (!item) return
  // 双击收藏（手机端主用）：搜索/收藏/文件系统视图统一切换收藏
  if (store.tab === 'trash') {
    // 回收站保留原行为：目录跳转到文件系统浏览，文件直接下载
    if (item.is_dir) openFsDir(item)
    else downloadItem(item)
    return
  }
  if (!item.id) {
    alert('该文件未索引，无法收藏（请先扫描根目录）')
    return
  }
  onToggleFav(item)
}
function onPreviewEnter() {
  const item = store.selected
  if (!item || !item.is_dir) return
  if (store.tab === 'fs') enterDir(item)
  else openFsDir(item)
}

/* ---------- 右键菜单 ---------- */
const ctxMenu = ref(null)
let closeCtxFn = null
function onCtx(e, item) {
  e.preventDefault()
  // 右键项未选中 → 单选它
  if (item) {
    const k = selKeyOf(item)
    if (!selKeys.value.has(k)) {
      selKeys.value = new Set([k])
      selAnchor = k
    }
    store.selected = item
    store.previewKey++
  }
  ctxMenu.value = {
    x: Math.min(e.clientX, window.innerWidth - 190),
    y: Math.min(e.clientY, window.innerHeight - 200),
    items: menuItems(),
  }
  if (closeCtxFn) window.removeEventListener('mousedown', closeCtxFn, true)
  closeCtxFn = () => { ctxMenu.value = null }
  window.addEventListener('mousedown', closeCtxFn, true)
}
function menuItems() {
  const sel = selectedItems()
  const n = sel.length
  const one = sel[0]
  if (store.tab === 'trash') {
    return [
      { key: 'restore', label: `恢复${n > 1 ? `（${n} 项）` : ''}`, icon: 'undo' },
      { key: 'purge', label: `彻底删除${n > 1 ? `（${n} 项）` : ''}`, icon: 'x', danger: true },
      { key: 'empty', label: '清空回收站', icon: 'trash', danger: true },
    ]
  }
  const items = []
  if (n === 1 && !one.is_dir && one.id) {
    items.push({ key: 'preview', label: '预览', icon: 'eye' })
  }
  const fav = one && one.fav_id
  items.push({
    key: 'fav', label: fav ? '取消收藏' : (n > 1 ? `收藏（${n} 项）` : '收藏'),
    icon: 'star',
  })
  if (n === 1 && !one.is_dir && one.id) {
    items.push({ key: 'download', label: '下载', icon: 'download' })
  }
  const deletable = sel.some(i => i.id)
  if (deletable) {
    items.push({ key: 'delete', label: `移入回收站${n > 1 ? `（${n} 项）` : ''}`, icon: 'trash', danger: true })
  }
  return items
}
function runCtx(key) {
  ctxMenu.value = null
  if (key === 'fav') return batchFav()
  if (key === 'delete') return batchDelete()
  if (key === 'restore') return batchRestore()
  if (key === 'purge') return batchPurge()
  if (key === 'empty') return trashEmpty()
  const sel = selectedItems()
  const one = sel[0]
  if (key === 'preview' && one) { store.selected = one; store.previewKey++ }
  if (key === 'download' && one) {
    const a = document.createElement('a')
    a.href = apiFiles.downloadUrl(one.id)
    a.download = one.name
    a.click()
  }
}

/* ---------- 保持滚动位置（内容微变不跳顶） ---------- */
let preservePos = 0
let keepPos = false
function markKeepPos() {
  preservePos = listRef.value ? listRef.value.getScrollTop() : 0
  keepPos = true
}

/* ---------- 批量操作 ---------- */
async function batchFav() {
  const items = selectedItems().filter(i => !i.fav_id && i.id)
  if (!items.length) return
  markKeepPos()
  for (const it of items) {
    try { await apiFavorites.toggle(it.id) } catch { /* 单条失败继续 */ }
  }
  onFilterChange()
}
const batchFavTitle = '批量收藏所选项目（已收藏的跳过）'
async function batchDelete() {
  const items = selectedItems()
  const withId = items.filter(i => i.id)
  if (!withId.length) {
    alert('所选项目中无已索引文件（未索引的文件需先扫描）')
    return
  }
  if (withId.length !== items.length) {
    alert(`${items.length - withId.length} 项未索引，无法删除；将删除其余 ${withId.length} 项`)
  }
  markKeepPos()
  // 移入回收站可随时恢复，不做二次确认（高频操作）
  const r = await apiFiles.batchDelete(withId.map(i => i.id))
  clearSelection()
  const moved = r.data?.moved || 0
  const errs = r.data?.errors || []
  // 移动失败的文件并未删除（仍在原位置），保留在列表并明确提示，避免"删了又恢复"的错觉
  const errSet = new Set(errs.map(e => e.rel_path))
  const okItems = withId.filter(i => !errSet.has(i.rel_path))
  if (errs.length) {
    const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
    alert(`有 ${errs.length} 项删除失败（文件被占用或网络共享不可写），已保留在列表中：${brief}`)
  }
  // 局部刷新：只更新删除点之后的缓存，不重建整个列表（避免白屏）
  const curTotal = store.tab === 'fs' ? store.fsTotal : store.searchTotal
  if (listRef.value) listRef.value.removeAndRefresh(okItems.map(i => i.id), Math.max(0, curTotal - moved))
  else onFilterChange()
  store.trashTotal += moved
  refreshStats()
}
async function batchRestore() {
  const items = selectedItems()
  if (!items.length) return
  markKeepPos()
  const r = await apiTrash.restore(items.map(i => i.id))
  const errs = r.data?.errors || []
  if (errs.length) {
    const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
    alert(`已恢复 ${r.data.restored} 项；${errs.length} 项失败（目标位置已存在同名文件），保留在回收站：${brief}`)
  } else {
    alert(`已恢复 ${r.data.restored} 项`)
  }
  clearSelection()
  const restored = r.data?.restored || 0
  // 只移除恢复成功的条目，失败条目保留在回收站列表
  const errSet = new Set(errs.map(e => e.rel_path))
  const okItems = items.filter(i => !errSet.has(i.rel_path))
  if (listRef.value) listRef.value.removeAndRefresh(okItems.map(i => i.id), Math.max(0, store.trashTotal - restored))
  else onFilterChange()
  refreshStats()
}
/* ---------- 自定义确认对话框（替代原生 confirm） ---------- */
const confirmBox = ref(null)   // { title, message, danger, resolve }
function askConfirm(title, message, danger = false) {
  return new Promise(resolve => {
    confirmBox.value = { title, message, danger, resolve }
  })
}
function confirmOk() {
  const c = confirmBox.value
  confirmBox.value = null
  if (c) c.resolve(true)
}
function confirmCancel() {
  const c = confirmBox.value
  confirmBox.value = null
  if (c) c.resolve(false)
}

async function batchPurge() {
  const items = selectedItems()
  if (!items.length) return
  const ok = await askConfirm('彻底删除', `确定彻底删除 ${items.length} 项？文件将从磁盘移除，此操作不可恢复。`, true)
  if (!ok) return
  markKeepPos()
  const r = await apiTrash.purge(items.map(i => i.id))
  const errs = r.data?.errors || []
  if (errs.length) {
    const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
    alert(`已彻底删除 ${r.data.purged} 项；${errs.length} 项失败（文件被占用或网络问题），保留在回收站：${brief}`)
  }
  clearSelection()
  const purged = r.data?.purged || 0
  const errSet = new Set(errs.map(e => e.rel_path))
  const okItems = items.filter(i => !errSet.has(i.rel_path))
  if (listRef.value) listRef.value.removeAndRefresh(okItems.map(i => i.id), Math.max(0, store.trashTotal - purged))
  else onFilterChange()
  refreshStats()
}
async function trashEmpty() {
  const ok = await askConfirm('清空回收站', '回收站将被清空，所有条目彻底删除（磁盘文件同时移除），此操作不可恢复。', true)
  if (!ok) return
  markKeepPos()
  const r = await apiTrash.empty()
  clearSelection()
  const purged = r.data?.purged || 0
  if (purged < store.trashTotal) {
    alert(`已清空 ${purged} 项；${store.trashTotal - purged} 项删除失败（文件被占用或网络问题），保留在回收站`)
    onFilterChange()   // 重拉显示真实剩余
  } else if (listRef.value) {
    listRef.value.clearAll(0)
  }
  store.trashTotal = purged
  refreshStats()
}

async function onToggleFav(item) {
  if (!item) return
  if (store.tab === 'favorites') {
    if (item.fav_id) {
      markKeepPos()
      await apiFavorites.remove(item.fav_id)
      onFilterChange()
    }
    return
  }
  const r = await apiFavorites.toggle(item.id)
  item.favorite = r.data.favorite
  if (r.data.favorite) store.favTotal++
  else store.favTotal = Math.max(0, store.favTotal - 1)
  // 列表数据是非响应式 Map：按引用替换条目对象 → :item 引用变化 → 卡片组件重新渲染（星标即时）
  if (listRef.value && !listRef.value.patchItemByRef(item, { favorite: r.data.favorite })) {
    listRef.value.bump() // 该页已释放未命中 → 兜底轻量重渲染
  }
}

async function pruneMissing() {
  const ok = await askConfirm('清除失效收藏', '将清除所有磁盘上已不存在的收藏记录。', true)
  if (!ok) return
  markKeepPos()
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
  // 焦点在输入控件内时不拦截：搜索框/输入框打字、退格、删除字符不受影响
  const t = e.target
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return
  if (e.key === 'Escape') {
    if (confirmBox.value) { confirmCancel(); return }
    if (ctxMenu.value) { ctxMenu.value = null; return }
    onEsc()
    return
  }
  // 搜索 / 收藏 / 文件系统界面：Delete 键批量移入回收站（高频无确认）
  if (e.key === 'Delete' && selKeys.value.size && store.tab !== 'trash') {
    e.preventDefault()
    batchDelete()
  }
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
.st-btn.danger { color: #e08a8a; border-color: #5e3a3a; }
.st-btn.danger:hover { background: rgba(224,92,92,.12); color: #ff9d9d; }
.accent-info { color: #6ab0ff; }
.st-mini {
  background: none; border: none; color: inherit; cursor: pointer;
  padding: 0 2px; font-size: 10px; opacity: .7;
}
.st-mini:hover { opacity: 1; }

/* 右键菜单 */
.ctx-menu {
  position: fixed; z-index: 200;
  min-width: 150px; background: #232529; border: 1px solid #3a3d44;
  border-radius: 8px; padding: 4px; box-shadow: 0 8px 28px rgba(0,0,0,.5);
  display: flex; flex-direction: column;
}
.ctx-item {
  display: flex; align-items: center; gap: 8px;
  background: none; border: none; color: #c9cdd4; text-align: left;
  padding: 7px 10px; border-radius: 6px; font-size: 12.5px; cursor: pointer;
}
.ctx-item:hover { background: rgba(76,139,245,.18); color: #fff; }
.ctx-item.danger { color: #e08a8a; }
.ctx-item.danger:hover { background: rgba(224,92,92,.16); color: #ff9d9d; }

/* 拉框多选 */
:deep(.box-select) {
  position: fixed; z-index: 100; pointer-events: none;
  background: rgba(76,139,245,.14); border: 1px solid #3d78e6;
  border-radius: 2px;
}

/* 自定义确认对话框 */
.ff-modal-mask {
  position: fixed; inset: 0; z-index: 300;
  background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center;
}
.ff-modal {
  background: #26282e; border: 1px solid #3a3d44; border-radius: 10px;
  padding: 18px 20px; width: 400px; max-width: 92vw;
  box-shadow: 0 12px 40px rgba(0,0,0,.6);
}
.ff-modal-title { font-size: 15px; font-weight: 600; margin-bottom: 10px; }
.ff-modal-msg { font-size: 13px; color: #b8bdc6; line-height: 1.6; margin-bottom: 16px; }
.ff-modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.ff-modal-actions .st-btn { min-width: 72px; }
</style>
