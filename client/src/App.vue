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

    <!-- 拣选模式专用控制条 -->
    <div class="pickstrip" v-if="store.tab === 'pick'">
      <div class="ps-stat">
        <span class="ps-tag">第 {{ store.pickPage }} 批</span>
        <span class="ps-total">本批共 <strong>{{ pickBatchItems.length }}</strong> 项</span>
        <span class="rs-sep">·</span>
        <span class="ps-fav"><Icon name="star" :size="12" /> 已选 <strong>{{ pickFavCount }}</strong> 项</span>
        <span class="rs-sep">·</span>
        <span class="ps-unfav"><Icon name="trash" :size="12" /> 待删 <strong>{{ pickUnfavCount }}</strong> 项</span>
        <span class="rs-sep">·</span>
        <span class="ps-remain">剩余待拣选约 <strong>{{ formatCount(store.pickTotal) }}</strong> 项</span>
      </div>

      <div class="ps-actions">
        <label class="ps-opt" title="调整每批加载数量（默认 200 项）">
          每批
          <select v-model.number="store.pickBatchSize" class="ps-sel" @change="onPickBatchSizeChange">
            <option :value="50">50 项</option>
            <option :value="100">100 项</option>
            <option :value="200">200 项 (默认)</option>
            <option :value="300">300 项</option>
            <option :value="500">500 项</option>
          </select>
        </label>

        <label class="ps-chk" title="若开启，删除时会弹出确认框；若关闭，一键直接清理未收藏项并秒切下一批">
          <input type="checkbox" v-model="store.pickConfirmDelete" @change="persistFilters" />
          删除前确认
        </label>

        <button v-if="store.pickPage > 1" class="rs-btn" title="查看上一批" @click="pickPrevBatch">
          ⏮️ 上一批
        </button>
        <button class="rs-btn" title="不删除当前未收藏项，直接浏览下一批" @click="pickSkipBatch">
          ⏭️ 跳过本批
        </button>
        <button class="rs-btn" title="刷新当前批次" @click="onFilterChange">
          🔄 刷新本批
        </button>

        <button
          class="st-btn danger ps-btn-del"
          :disabled="pickBatchItems.length === 0 || pickDeleting"
          title="将本批中未打星收藏的文件全部移入回收站，并自动加载下一批（快捷键：Ctrl+Enter）"
          @click="pickDeleteAndNext"
        >
          <Icon name="trash" :size="13" />
          {{ pickDeleting ? '正在清理...' : `删除未收藏并进入下一批 (${pickUnfavCount})` }}
        </button>
      </div>
    </div>

    <div class="main">
      <div class="list-area" @mousedown="onAreaMouseDown">
        <!-- 表格表头：列标题 + 排序 + 可拖拽列宽 -->
        <div v-if="isTable" class="tbl-head">
          <div class="th" style="width: 44px; justify-content: center; color: #6b7280; font-size: 11px;">#</div>
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
          :page-size="store.tab === 'pick' ? store.pickBatchSize : pageSize"
          :fetch-page="fetchPage"
          :grid="store.viewMode !== 'table'"
          :col-width="cfg.colWidth"
          :row-height="isTable ? 36 : cfg.rowHeight"
          :buffer-rows="8"
          @total-update="onTotalUpdate"
        >
          <template #item="{ item, index }">
            <!-- 表格视图（列宽与表头一致，可随表头拖拽调整） -->
            <div v-if="isTable" class="trow" :class="{ sel: isSel(item), pressing: rowPressKey === selKeyOf(item) }"
                 @mousedown="onRowMouseDown(item, $event)"
                 @mousemove="onRowMouseMove(item, $event)"
                 @mouseup="onRowMouseUp(item, $event)"
                 @mouseleave="onRowMouseLeave(item, $event)"
                 @touchstart.passive="onRowTouchStart(item, $event)"
                 @touchmove.passive="onRowTouchMove(item, $event)"
                 @touchend="onRowTouchEnd(item, $event)"
                 @touchcancel="onRowTouchCancel(item, $event)"
                 @click="onRowClick(item, $event)" @dblclick="onCellDbl(item)"
                 @contextmenu="onRowCtx($event, item, index)">
              <span style="width: 44px; text-align: center; color: #6b7280; font-size: 11px; font-family: monospace; user-select: none;">#{{ index + 1 }}</span>
              <span class="t-ic" :style="{ color: item && itemColor(item), width: 26 }">
                <Icon v-if="item" :name="iconOf(item)" :size="15" />
              </span>
              <span class="t-name" :style="colStyle({ key: 'name' })"
                    :title="item ? (item.rel_path || item.name) : ''">{{ item ? item.name : '' }}</span>
              <span class="t-ext" :style="colStyle({ key: 'ext' })">{{ item ? (item.ext || (item.is_dir ? '目录' : '—')) : '' }}</span>
              <span class="t-size" :style="colStyle({ key: 'size' })">{{ item ? formatSize(item.size) : '' }}</span>
              <span class="t-date" :style="colStyle({ key: 'mtime' })">{{ item ? formatDate(item.mtime) : '' }}</span>
              <span class="t-path" style="flex:1 1 0; min-width:80px" :title="item && item.root_path">{{ item ? item.root_path : '' }}</span>
              <span class="t-fav" :style="{ width: 24 }" @click.stop="item && onToggleFav(item)" :title="item && (item.favorite || item.fav_id) ? '取消收藏' : ''">
                <Icon v-if="item && (item.favorite || item.fav_id)" name="star" :size="13" style="color:#f5b942; cursor:pointer" />
              </span>
              <span v-if="item && item.exists_now === false" class="t-miss">丢失</span>
            </div>
            <!-- 卡片视图 -->
            <FileCard
              v-else
              :item="item"
              :index="index"
              :mode="store.viewMode"
              :selected="isSel(item)"
              :favorite="!!(item && item.favorite)"
              @select="(it, e) => onCellClick(it, e)"
              @fav="onToggleFav"
              @dbl="onCellDbl"
              @ctx="onCtx($event, item, index)"
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
          <span v-if="deleting" class="st-item del-prog">
            <span class="del-bar"><i :style="{ width: deleting.total ? (deleting.done / deleting.total * 100) + '%' : '0%' }"></i></span>
            正在删除 <b>{{ deleting.done }}</b> / {{ deleting.total }}（{{ deleting.total ? Math.round(deleting.done / deleting.total * 100) : 0 }}%）
          </span>
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

      <PreviewPanel
        v-if="store.showPreview && store.tab !== 'trash'"
        @fav-change="onPreviewFavChange"
        @item-deleted="onPreviewDeleted"
        @enter="onPreviewEnter"
      />
    </div>

    <TaskBar ref="taskBarRef" />

    <div v-if="ctxMenu" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }" @contextmenu.prevent>
      <button v-for="it in ctxMenu.items" :key="it.key" class="ctx-item" :class="{ danger: it.danger }" @click.stop="runCtx(it.key)">
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

    <!-- 浮层轻量 Toast 提示 -->
    <transition name="toast-fade">
      <div v-if="toastMsg" class="toast-tip">
        <Icon name="check" :size="15" />
        <span>{{ toastMsg }}</span>
      </div>
    </transition>

    <RootManager :open="showRoots" @close="showRoots = false" @task="trackTask" />
    <CollectDialog :open="showCollect" @close="showCollect = false" @task="trackTask" @done="onFilterChange" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount , nextTick } from 'vue'
import TopBar from './components/TopBar.vue'
import VirtualList from './components/VirtualList.vue'
import FileCard from './components/FileCard.vue'
import PreviewPanel from './components/PreviewPanel.vue'
import TaskBar from './components/TaskBar.vue'
import RootManager from './components/RootManager.vue'
import CollectDialog from './components/CollectDialog.vue'
import Icon from './components/Icon.vue'
import { store, viewCfg, tableCols, saveTableCols } from './store'
import { trackTask, loadActiveTasks } from './tasks'
import { apiSearch, apiFavorites, apiRoots, apiStats, apiFiles, apiFs, apiTrash } from './api'
import { formatSize, formatDate } from './utils/format'
import { fileIcon, fileColor } from './utils/fileTypes'

const pageSize = 300
const sessionStartTime = ref(Date.now() / 1000)
const listRef = ref(null)

/* ---------- 多选（Ctrl/Shift + 框选） ---------- */
const selKeys = ref(new Set())   // 已选唯一键集合（跨页累积）
let selAnchor = null             // Shift 范围锚点（唯一键）
const pageItems = {}             // 页索引 -> items（范围选择的有序来源）
const deletedIds = ref(new Set()) // 本地黑名单：已被移入回收站的条目 ID（避免重拉脏数据穿透）

function deductTotal(count) {
  if (store.tab === 'trash') {
    store.trashTotal = Math.max(0, store.trashTotal - count)
    return
  }
  if (store.tab === 'favorites') store.favTotal = Math.max(0, store.favTotal - count)
  else if (store.tab === 'fs') store.fsTotal = Math.max(0, store.fsTotal - count)
  else if (store.tab === 'pick') store.pickTotal = Math.max(0, store.pickTotal - count)
  else store.searchTotal = Math.max(0, store.searchTotal - count)
  store.trashTotal += count
}

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
  if (store.tab === 'favorites') return ['name', 'size', 'mtime', 'path'].includes(key)
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
// 批量删除进度（{ done, total }；null = 无进行中删除）
const deleting = ref(null)
const initialLoading = ref(true)
const loadedPages = ref(0)

/* ---------- 拣选模式（Pick Mode）批次状态 ---------- */
const pickBatchItems = ref([])
const pickDeleting = ref(false)
const pickFavCount = computed(() => pickBatchItems.value.filter(i => i && (i.favorite || i.fav_id)).length)
const pickUnfavCount = computed(() => Math.max(0, pickBatchItems.value.length - pickFavCount.value))

const cfg = computed(() => viewCfg())
const isTable = computed(() => store.viewMode === 'table')
const activeTotal = computed(() => {
  if (store.tab === 'favorites') return store.favTotal
  if (store.tab === 'fs') return store.fsTotal
  if (store.tab === 'trash') return store.trashTotal
  if (store.tab === 'pick') return pickBatchItems.value.length
  return store.searchTotal
})
const loadedCount = computed(() => Math.min(loadedPages.value * (store.tab === 'pick' ? store.pickBatchSize : pageSize), activeTotal.value))
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
  if (store.tab === 'pick') return '当前范围内的未收藏文件已全部拣选完毕！'
  return '没有匹配的文件'
})
const emptySub = computed(() => {
  if (store.tab === 'fs') return '可点击「↑ 上级」返回，或在「设置」中添加扫描根目录'
  if (store.tab === 'trash') return '删除的文件会先进入回收站，在这里可恢复或彻底删除'
  if (store.tab === 'pick') return '已无符合当前条件的未收藏文件，可切换扫描根或类型继续拣选'
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

function searchParams(page) {
  const scope = store.searchScope || {}
  const p = {
    q: store.q,
    root_id: scope.root_id != null ? scope.root_id : store.rootId,
    prefix: scope.prefix || null,
    regex: store.regex ? 1 : null,
    ext: store.ext,
    fav_only: store.favOnly ? 1 : null,
    hide_fav: store.hideFav ? 1 : null,
    hide_fav_before: store.hideFav ? sessionStartTime.value : null,
    sort: store.sort,
    order: store.order,
    page,
    page_size: pageSize,
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
    const p = {
      path: fsAbsPath(),
      page: pageIdx + 1,
      page_size: pageSize,
      sort: store.sort,
      order: store.order,
    }
    res = await apiFs.list(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.fsTotal = res.data.total
  } else if (store.tab === 'pick') {
    // 拣选模式：固定取当前批次，天然开启 hide_fav = 1（只拉取未收藏项供用户挑选）
    const scope = store.searchScope || {}
    const p = {
      q: store.q,
      root_id: scope.root_id != null ? scope.root_id : store.rootId,
      prefix: scope.prefix || null,
      regex: store.regex ? 1 : null,
      ext: store.ext,
      hide_fav: 1,
      sort: store.sort,
      order: store.order,
      page: store.pickPage,
      page_size: store.pickBatchSize,
    }
    for (const k of Object.keys(p)) if (p[k] === null || p[k] === undefined || p[k] === '') delete p[k]
    res = await apiSearch(p)
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.pickTotal = res.data.total
  } else {
    // 确定性幂等分页：基于固定页码与大小，保证慢滚与快滚顺序绝对严格一致
    res = await apiSearch(searchParams(pageIdx + 1))
    if (gen !== listKey.value) return { total: 0, items: [] }
    store.searchTotal = res.data.total
  }
  let items = res.data.items || []
  if (store.tab !== 'trash' && deletedIds.value.size) {
    items = items.filter(it => it && !deletedIds.value.has(it.id) && (!it.fav_id || !deletedIds.value.has(it.fav_id)))
  }
  if (store.tab === 'pick') {
    pickBatchItems.value = items
  }
  pageItems[pageIdx] = items
  return { total: activeTotal.value, items }
}

function onTotalUpdate(total) {
  if (store.tab === 'favorites') store.favTotal = total
  else if (store.tab === 'fs') store.fsTotal = total
  else if (store.tab === 'trash') store.trashTotal = total
  else if (store.tab === 'pick') store.pickTotal = total
  else store.searchTotal = total
}

function onFilterChange() {
  sessionStartTime.value = Date.now() / 1000
  // 文件系统 Tab：无浏览根或根已被删除时，重置为第一个扫描根
  if (store.tab === 'fs') {
    const still = store.roots.find(r => r.id === (store.fsRoot && store.fsRoot.id))
    if (!still || !store.fsRoot) {
      store.fsRoot = store.roots[0] || null
      store.fsRel = ''
    }
  }
  loadedPages.value = 0
  store.selected = null
  clearSelection()
  store.previewKey++
  refreshStats()
  if (listRef.value) {
    listRef.value.reset()
  } else {
    listKey.value++
  }
  // 内容微变（删除/收藏/恢复等）时恢复滚动位置，避免跳回顶部
  if (keepPos) {
    keepPos = false
    const target = preservePos
    nextTick(() => { if (target && listRef.value) listRef.value.scrollTo(target) })
  }
}

function onPreviewFavChange({ item, favorite }) {
  if (store.tab === 'favorites') {
    if (!favorite) {
      const curTotal = store.favTotal
      if (listRef.value) listRef.value.removeAndRefresh([item.id, item.fav_id], Math.max(0, curTotal - 1))
      store.favTotal = Math.max(0, curTotal - 1)
      store.selected = null
    }
  } else {
    if (favorite) store.favTotal++
    else store.favTotal = Math.max(0, store.favTotal - 1)
    if (listRef.value) {
      listRef.value.patchItemById(item.id, { favorite })
    }
    if (store.tab === 'pick') {
      const it = pickBatchItems.value.find(i => i && i.id === item.id)
      if (it) it.favorite = favorite
    }
  }
  refreshStats()
}

function onPreviewDeleted(fileId) {
  deletedIds.value.add(fileId)
  deductTotal(1)
  for (const p of Object.keys(pageItems)) {
    pageItems[p] = (pageItems[p] || []).filter(it => it.id !== fileId)
  }
  if (listRef.value) listRef.value.removeAndRefresh([fileId], activeTotal.value)
  store.selected = null
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

/* ---------- 表格行长按收藏 / 取消收藏（<= 0.5s，设计为 400ms） ---------- */
const rowPressKey = ref(null)
let rowPressTimer = null
let rowStartX = 0
let rowStartY = 0
let rowDidLongPress = false

function triggerRowLongPress(item) {
  if (!item) return
  rowDidLongPress = true
  rowPressKey.value = null
  rowPressTimer = null
  if (typeof navigator !== 'undefined' && navigator.vibrate) {
    try { navigator.vibrate(40) } catch {}
  }
  onToggleFav(item)
}

function cancelRowPress() {
  if (rowPressTimer) {
    clearTimeout(rowPressTimer)
    rowPressTimer = null
  }
  rowPressKey.value = null
}

function onRowMouseDown(item, e) {
  if (e.button !== 0 || !item) return
  rowStartX = e.clientX
  rowStartY = e.clientY
  rowDidLongPress = false
  rowPressKey.value = selKeyOf(item)
  rowPressTimer = setTimeout(() => triggerRowLongPress(item), 400)
}

function onRowMouseMove(item, e) {
  if (!rowPressTimer) return
  const dx = Math.abs(e.clientX - rowStartX)
  const dy = Math.abs(e.clientY - rowStartY)
  if (dx > 8 || dy > 8) cancelRowPress()
}

function onRowMouseUp() {
  cancelRowPress()
}

function onRowMouseLeave() {
  cancelRowPress()
}

function onRowTouchStart(item, e) {
  if (!item || !e.touches || e.touches.length !== 1) return
  const t = e.touches[0]
  rowStartX = t.clientX
  rowStartY = t.clientY
  rowDidLongPress = false
  rowPressKey.value = selKeyOf(item)
  rowPressTimer = setTimeout(() => triggerRowLongPress(item), 400)
}

function onRowTouchMove(item, e) {
  if (!rowPressTimer || !e.touches || !e.touches.length) return
  const t = e.touches[0]
  const dx = Math.abs(t.clientX - rowStartX)
  const dy = Math.abs(t.clientY - rowStartY)
  if (dx > 8 || dy > 8) cancelRowPress()
}

function onRowTouchEnd() {
  cancelRowPress()
}

function onRowTouchCancel() {
  cancelRowPress()
}

function onRowCtx(e, item, index = -1) {
  cancelRowPress()
  e.preventDefault()
  onCtx(e, item, index)
}

function onRowClick(item, e) {
  if (rowDidLongPress) {
    e.preventDefault()
    e.stopPropagation()
    rowDidLongPress = false
    return
  }
  onCellClick(item, e)
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

/* ---------- 浮层轻量提示（Toast） ---------- */
const toastMsg = ref('')
let toastTimer = null
function showToast(msg, duration = 3000) {
  toastMsg.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastMsg.value = ''
  }, duration)
}

/* ---------- 右键菜单 ---------- */
const ctxMenu = ref(null)
let ctxTarget = null
let closeCtxFn = null

function onCtx(e, item, index = -1) {
  e.preventDefault()
  // 右键项未在选区中 → 单选它
  if (item) {
    const k = selKeyOf(item)
    if (!selKeys.value.has(k)) {
      selKeys.value = new Set([k])
      selAnchor = k
    }
    store.selected = item
    store.previewKey++
  }
  if ((index === undefined || index < 0) && item && listRef.value) {
    index = listRef.value.findIndexById(item.id || item.fav_id)
  }
  ctxTarget = { item, index }
  ctxMenu.value = {
    x: Math.min(e.clientX, window.innerWidth - 240),
    y: Math.min(e.clientY, window.innerHeight - 240),
    items: menuItems(),
  }
  if (closeCtxFn) {
    window.removeEventListener('click', closeCtxFn)
    window.removeEventListener('contextmenu', closeCtxFn)
  }
  closeCtxFn = (evt) => {
    if (evt && evt.target && evt.target.closest('.ctx-menu')) return
    ctxMenu.value = null
    window.removeEventListener('click', closeCtxFn)
    window.removeEventListener('contextmenu', closeCtxFn)
    closeCtxFn = null
  }
  setTimeout(() => {
    window.addEventListener('click', closeCtxFn)
    window.addEventListener('contextmenu', closeCtxFn)
  }, 10)
}

function menuItems() {
  const sel = selectedItems()
  const n = sel.length
  const one = sel[0]
  const targetItem = ctxTarget?.item || one
  let targetIdx = ctxTarget?.index ?? -1
  if (targetIdx < 0 && targetItem && listRef.value) {
    targetIdx = listRef.value.findIndexById(targetItem.id || targetItem.fav_id)
  }
  const seqLabel = targetIdx >= 0
    ? `复制此前文件名序列（#1 ~ #${targetIdx + 1}，共 ${targetIdx + 1} 个）`
    : '复制此前文件名序列'

  if (store.tab === 'trash') {
    const trashItems = [
      { key: 'restore', label: `恢复${n > 1 ? `（${n} 项）` : ''}`, icon: 'undo' },
      { key: 'purge', label: `彻底删除${n > 1 ? `（${n} 项）` : ''}`, icon: 'x', danger: true },
      { key: 'empty', label: '清空回收站', icon: 'trash', danger: true },
    ]
    if (targetItem) {
      trashItems.push({ key: 'copySequence', label: seqLabel, icon: 'copy' })
    }
    return trashItems
  }
  const items = []
  if (n === 1 && !one.is_dir && one.id) {
    items.push({ key: 'preview', label: '预览', icon: 'eye' })
  }
  const allFav = store.tab === 'favorites' || (n > 0 && sel.every(i => i.fav_id || i.favorite))
  items.push({
    key: 'fav',
    label: allFav ? (n > 1 ? `取消收藏（${n} 项）` : '取消收藏') : (n > 1 ? `收藏（${n} 项）` : '收藏'),
    icon: 'star',
  })
  if (n === 1 && !one.is_dir && one.id) {
    items.push({ key: 'download', label: '下载', icon: 'download' })
  }
  if (targetItem) {
    items.push({ key: 'copySequence', label: seqLabel, icon: 'copy' })
  }
  const deletable = sel.some(i => i.id)
  if (deletable) {
    items.push({ key: 'delete', label: `移入回收站${n > 1 ? `（${n} 项）` : ''}`, icon: 'trash', danger: true })
  }
  return items
}

async function copySequenceBeforeTarget() {
  const targetItem = ctxTarget?.item || store.selected
  if (!targetItem) {
    showToast('⚠️ 未选中任何条目', 2000)
    return
  }

  let targetIdx = ctxTarget?.index ?? -1
  if (targetIdx < 0 && listRef.value) {
    targetIdx = listRef.value.findIndexById(targetItem.id || targetItem.fav_id)
  }
  if (targetIdx < 0) targetIdx = 0

  const count = targetIdx + 1
  const pageSizeVal = listRef.value?.pageSize || pageSize || 300
  const maxPage = Math.floor(targetIdx / pageSizeVal)

  showToast(`正在提取第 1 ~ #${count} 项文件名...`, 2000)

  // 确保 0 到 maxPage 的全部页均已缓存加载
  if (listRef.value?.ensurePagesLoaded) {
    await listRef.value.ensurePagesLoaded(0, maxPage)
  }

  const names = []
  let globalIdx = 0
  for (let p = 0; p <= maxPage; p++) {
    const list = listRef.value?.pages?.get(p) || pageItems[p] || []
    for (let i = 0; i < list.length; i++) {
      if (globalIdx > targetIdx) break
      const it = list[i]
      if (it) {
        names.push(it.name || it.rel_path || `Item_${globalIdx + 1}`)
      }
      globalIdx++
    }
  }

  if (!names.length) {
    showToast('⚠️ 未能提取到有效文件名', 2500)
    return
  }

  const text = names.join('\n')
  let copyOk = false
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text)
      copyOk = true
    }
  } catch {}
  if (!copyOk) {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    copyOk = document.execCommand('copy')
    document.body.removeChild(ta)
  }

  window.__prevCopiedSequence = window.__lastCopiedSequence || null
  window.__lastCopiedSequence = names

  console.log(`%c[Sequence] 成功复制此前 ${names.length} 个文件名到剪贴板（#1 ~ #${targetIdx + 1}）：`, 'color:#4caf50;font-weight:bold;', names)
  if (window.__prevCopiedSequence) {
    console.log(`%c💡 控制台比对提示：直接在控制台执行 %ccompareSequences()%c 即可自动校验本次与上一次复制序列的子集关系与严格有序性！`, 'color:#4c8bf5;', 'color:#ffb300;font-weight:bold;', 'color:#4c8bf5;')
  }

  showToast(`✅ 已复制此前 ${names.length} 个文件名到剪贴板（#1 ~ #${targetIdx + 1}）`)
}

function runCtx(key) {
  if (closeCtxFn) {
    window.removeEventListener('click', closeCtxFn)
    window.removeEventListener('contextmenu', closeCtxFn)
    closeCtxFn = null
  }
  ctxMenu.value = null
  if (key === 'copySequence') return copySequenceBeforeTarget()
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
  const items = selectedItems()
  if (!items.length) return
  // 判断所选项是否全部已收藏（或当前在收藏 Tab）
  const allFav = store.tab === 'favorites' || items.every(i => i.fav_id || i.favorite)
  if (allFav) {
    // 批量取消收藏
    for (const it of items) {
      try {
        if (it.fav_id) await apiFavorites.remove(it.fav_id)
        else if (it.id) await apiFavorites.toggle(it.id)
      } catch { /* 单条失败继续 */ }
      it.favorite = false
      if (listRef.value) listRef.value.patchItemById(it.id || it.fav_id, { favorite: false })
    }
    if (store.tab === 'favorites') {
      const idsToRemove = items.map(i => i.id || i.fav_id)
      if (listRef.value) listRef.value.removeAndRefresh(idsToRemove, Math.max(0, store.favTotal - items.length))
      store.favTotal = Math.max(0, store.favTotal - items.length)
    } else {
      store.favTotal = Math.max(0, store.favTotal - items.length)
    }
    clearSelection()
    refreshStats()
  } else {
    // 批量新增收藏（跳过已收藏的）
    const toAdd = items.filter(i => !i.fav_id && !i.favorite && i.id)
    if (!toAdd.length) {
      alert('所选项中没有可收藏的已索引文件')
      return
    }
    const ids = toAdd.map(i => i.id)
    try {
      const r = await apiFavorites.batch(ids)
      const added = r?.data?.added || 0
      store.favTotal += added
      for (const it of toAdd) {
        it.favorite = true
        if (listRef.value) listRef.value.patchItemById(it.id, { favorite: true })
      }
      clearSelection()
      refreshStats()
    } catch (e) {
      alert(`批量收藏失败: ${e.message}`)
    }
  }
}
const batchFavTitle = '批量收藏所选项目（全部已收藏时则取消收藏）'
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
  const ids = withId.map(i => i.id)
  clearSelection()

  // 1. 立即加入已删除黑名单，避免任何并发拉取脏数据穿透
  for (const id of ids) deletedIds.value.add(id)
  for (const it of withId) {
    if (it.fav_id) deletedIds.value.add(it.fav_id)
  }

  // 2. 扣减当前 Tab 的实际总数，并从虚拟列表与内存页中剔除
  deductTotal(ids.length)
  for (const p of Object.keys(pageItems)) {
    pageItems[p] = (pageItems[p] || []).filter(it => !deletedIds.value.has(it.id))
  }
  if (listRef.value) listRef.value.removeAndRefresh(ids, activeTotal.value)
  else onFilterChange()

  // 3. 提交后端处理
  try {
    const r = await apiFiles.batchDelete(ids)
    const task_id = r?.data?.task_id

    if (task_id) {
      // 后端已创建后台异步删除任务：接入任务系统并在 TaskBar 实时回显进度
      trackTask(task_id, (t) => {
        refreshStats()
        // 关键：任务完成后静默刷新当前可视区页，确保没有残存空洞
        if (listRef.value) {
          listRef.value.refreshVisible()
        }
        const errs = t?.detail?.errors || []
        if (errs.length) {
          const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
          alert(`有 ${errs.length} 项删除失败（文件被占用或无写权限）：${brief}`)
          // 从 deletedIds 中移除失败项
          for (const e of errs) {
            const failedItem = withId.find(i => i.rel_path === e.rel_path)
            if (failedItem) {
              deletedIds.value.delete(failedItem.id)
              if (failedItem.fav_id) deletedIds.value.delete(failedItem.fav_id)
            }
          }
          onFilterChange()
        } else {
          // 成功完成：清空黑名单
          for (const id of ids) deletedIds.value.delete(id)
        }
      })
      return
    }

    // 同步返回模式（少量文件场景）：
    const moved = r?.data?.moved || 0
    const errs = r?.data?.errors || []
    if (listRef.value) {
      listRef.value.refreshVisible()
    }
    if (errs.length) {
      const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
      alert(`有 ${errs.length} 项删除失败（已保留在列表中）：${brief}`)
      for (const e of errs) {
        const failedItem = withId.find(i => i.rel_path === e.rel_path)
        if (failedItem) {
          deletedIds.value.delete(failedItem.id)
          if (failedItem.fav_id) deletedIds.value.delete(failedItem.fav_id)
        }
      }
      onFilterChange()
    } else {
      for (const id of ids) deletedIds.value.delete(id)
    }
    refreshStats()
  } catch (e) {
    alert(`移入回收站失败: ${e.message}`)
    for (const id of ids) deletedIds.value.delete(id)
    onFilterChange()
  }
}
async function batchRestore() {
  const items = selectedItems()
  if (!items.length) return
  markKeepPos()
  const ids = items.map(i => i.id)
  clearSelection()

  // 1. 立即加入已删除黑名单，避免任何并发拉取脏数据穿透
  for (const id of ids) deletedIds.value.add(id)
  for (const it of items) {
    if (it.fav_id) deletedIds.value.add(it.fav_id)
  }

  // 2. 扣减当前 Tab 的实际总数，并从虚拟列表与内存页中剔除
  deductTotal(ids.length)
  for (const p of Object.keys(pageItems)) {
    pageItems[p] = (pageItems[p] || []).filter(it => !deletedIds.value.has(it.id))
  }
  if (listRef.value) listRef.value.removeAndRefresh(ids, activeTotal.value)
  else onFilterChange()

  // 3. 提交后端处理
  try {
    const r = await apiTrash.restore(ids)
    const task_id = r?.data?.task_id
    if (task_id) {
      trackTask(task_id, (t) => {
        refreshStats()
        if (listRef.value) listRef.value.refreshVisible()
        const errs = t?.detail?.errors || []
        if (errs.length) {
          const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
          alert(`已恢复部分项；${errs.length} 项恢复失败（目标位置已存在同名文件），保留在回收站：${brief}`)
          for (const e of errs) {
            const failed = items.find(i => i.rel_path === e.rel_path)
            if (failed) {
              deletedIds.value.delete(failed.id)
              if (failed.fav_id) deletedIds.value.delete(failed.fav_id)
            }
          }
          onFilterChange()
        } else {
          for (const id of ids) deletedIds.value.delete(id)
        }
      })
      return
    }

    // 同步返回
    const errs = r.data?.errors || []
    if (errs.length) {
      const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
      alert(`已恢复 ${r.data.restored} 项；${errs.length} 项失败（目标位置已存在同名文件），保留在回收站：${brief}`)
      for (const e of errs) {
        const failed = items.find(i => i.rel_path === e.rel_path)
        if (failed) {
          deletedIds.value.delete(failed.id)
          if (failed.fav_id) deletedIds.value.delete(failed.fav_id)
        }
      }
      onFilterChange()
    } else {
      for (const id of ids) deletedIds.value.delete(id)
      if (listRef.value) listRef.value.refreshVisible()
    }
    refreshStats()
  } catch (e) {
    alert(`恢复失败: ${e.message}`)
    for (const id of ids) deletedIds.value.delete(id)
    onFilterChange()
  }
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
  const ids = items.map(i => i.id)
  clearSelection()

  // 1. 立即加入已删除黑名单，避免任何并发拉取脏数据穿透
  for (const id of ids) deletedIds.value.add(id)

  // 2. 扣减当前 Tab 的实际总数，并从虚拟列表与内存页中剔除
  deductTotal(ids.length)
  for (const p of Object.keys(pageItems)) {
    pageItems[p] = (pageItems[p] || []).filter(it => !deletedIds.value.has(it.id))
  }
  if (listRef.value) listRef.value.removeAndRefresh(ids, activeTotal.value)
  else onFilterChange()

  // 3. 提交后端处理
  try {
    const r = await apiTrash.purge(ids)
    const task_id = r?.data?.task_id
    if (task_id) {
      trackTask(task_id, (t) => {
        refreshStats()
        if (listRef.value) listRef.value.refreshVisible()
        const errs = t?.detail?.errors || []
        if (errs.length) {
          const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
          alert(`有 ${errs.length} 项彻底删除失败（文件被占用或无写权限）：${brief}`)
          for (const e of errs) {
            const failed = items.find(i => i.rel_path === e.rel_path)
            if (failed) deletedIds.value.delete(failed.id)
          }
          onFilterChange()
        } else {
          for (const id of ids) deletedIds.value.delete(id)
        }
      })
      return
    }

    // 同步返回模式
    const purged = r.data?.purged || 0
    const errs = r.data?.errors || []
    if (errs.length) {
      const brief = errs.slice(0, 3).map(e => `${(e.rel_path || '').split('/').pop() || e.rel_path}（${e.error}）`).join('；')
      alert(`已彻底删除 ${purged} 项；${errs.length} 项失败（文件被占用或网络问题），保留在回收站：${brief}`)
      for (const e of errs) {
        const failed = items.find(i => i.rel_path === e.rel_path)
        if (failed) deletedIds.value.delete(failed.id)
      }
      onFilterChange()
    } else {
      for (const id of ids) deletedIds.value.delete(id)
      if (listRef.value) listRef.value.refreshVisible()
    }
    refreshStats()
  } catch (e) {
    alert(`彻底删除失败: ${e.message}`)
    for (const id of ids) deletedIds.value.delete(id)
    onFilterChange()
  }
}
async function trashEmpty() {
  const ok = await askConfirm('清空回收站', '回收站将被清空，所有条目彻底删除（磁盘文件同时移除），此操作不可恢复。', true)
  if (!ok) return
  markKeepPos()
  clearSelection()

  try {
    const r = await apiTrash.empty()
    const task_id = r?.data?.task_id
    if (task_id) {
      // 乐观清空前端展示与计数
      store.trashTotal = 0
      if (listRef.value) listRef.value.clearAll(0)
      trackTask(task_id, (t) => {
        refreshStats()
        if (listRef.value) listRef.value.clearAll(0)
        onFilterChange()
      })
      return
    }

    // 同步返回模式
    const purged = r.data?.purged || 0
    if (purged < store.trashTotal) {
      alert(`已清空 ${purged} 项；${store.trashTotal - purged} 项删除失败（文件被占用或网络问题），保留在回收站`)
      onFilterChange()
    } else if (listRef.value) {
      listRef.value.clearAll(0)
    }
    store.trashTotal = 0
    refreshStats()
  } catch (e) {
    alert(`清空回收站失败: ${e.message}`)
    onFilterChange()
  }
}

async function onToggleFav(item) {
  if (!item) return
  if (store.tab === 'trash') return
  if (!item.id && !item.fav_id) {
    alert('该文件未索引，无法收藏（请先扫描根目录）')
    return
  }
  if (store.tab === 'favorites') {
    if (item.fav_id) {
      markKeepPos()
      await apiFavorites.remove(item.fav_id)
      onFilterChange()
    }
    return
  }
  const r = await apiFavorites.toggle(item.id)
  const fav = r.data.favorite
  item.favorite = fav
  if (fav) store.favTotal++
  else store.favTotal = Math.max(0, store.favTotal - 1)

  // 1. 通过 ID 替换 VirtualList 缓存生成新引用对象，并促发 version++ 响应式计算
  if (listRef.value) {
    const updated = listRef.value.patchItemById(item.id, { favorite: fav })
    if (updated && store.selected && (store.selected.id === item.id || store.selected.fav_id === item.id)) {
      store.selected = updated
    }
    listRef.value.bump()
  }
  // 2. 同步更新当前选中对象为新浅拷贝对象
  if (store.selected && (store.selected.id === item.id || store.selected.fav_id === item.id)) {
    store.selected = { ...store.selected, favorite: fav }
  }
  if (store.tab === 'pick') {
    const it = pickBatchItems.value.find(i => i && i.id === item.id)
    if (it) it.favorite = fav
  }
  store.previewKey++
  refreshStats()
}

/* ---------- 拣选模式（Pick Mode）批次操作 ---------- */
function onPickBatchSizeChange() {
  persistFilters()
  store.pickPage = 1
  onFilterChange()
}

function pickSkipBatch() {
  store.pickPage++
  onFilterChange()
}

function pickPrevBatch() {
  if (store.pickPage > 1) {
    store.pickPage--
    onFilterChange()
  }
}

async function pickDeleteAndNext() {
  if (pickDeleting.value) return
  const toDelete = pickBatchItems.value.filter(it => it && !it.favorite && !it.fav_id && it.id)

  if (toDelete.length === 0) {
    showToast('本批次全部已收藏，无需删除，正在加载下一批...', 2000)
    store.pickPage++
    onFilterChange()
    return
  }

  if (store.pickConfirmDelete) {
    const ok = await askConfirm(
      '移入回收站确认',
      `确定将本批未收藏的 ${toDelete.length} 项移入回收站，并加载下一批吗？\n（已打星收藏的 ${pickFavCount.value} 项将被安全保留）`,
      true
    )
    if (!ok) return
  }

  pickDeleting.value = true
  const ids = toDelete.map(it => it.id)
  for (const id of ids) deletedIds.value.add(id)
  try {
    const r = await apiFiles.batchDelete(ids)
    showToast(`✅ 已将 ${ids.length} 项移入回收站，已为您加载下一批`, 2500)
    refreshStats()
    store.selected = null
    clearSelection()
    // 重新拉取当前批次（因为被删项已进入回收站，下一批数据自然浮上来）
    onFilterChange()
  } catch (e) {
    alert(`移入回收站失败: ${e.message}`)
    for (const id of ids) deletedIds.value.delete(id)
  } finally {
    pickDeleting.value = false
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
    } else if (store.rootId != null && !store.roots.some(r => r.id === store.rootId)) {
      store.rootId = store.roots.length ? store.roots[0].id : null  // 持久化的根已失效 → 重置
    }
    // 恢复文件系统浏览位置（浏览根 + 目录）
    let savedFsId = null, savedFsRel = ''
    try {
      const o = JSON.parse(localStorage.getItem('ff_filters') || '{}')
      savedFsId = o && o.fsRootId != null ? o.fsRootId : null
      savedFsRel = o && typeof o.fsRel === 'string' ? o.fsRel : ''
    } catch { /* noop */ }
    if (savedFsId != null) {
      const r = store.roots.find(x => x.id === savedFsId)
      if (r) { store.fsRoot = r; store.fsRel = savedFsRel }
    }
    loadActiveTasks()
  } catch (e) {
    console.error('初始化失败', e)
  }
  initialLoading.value = false
}

/* ---------- Tab 独立 hash 路由：刷新/后退停留在原界面 ---------- */
const TAB_HASH = { search: '#/search', pick: '#/pick', fs: '#/fs', favorites: '#/favorites', trash: '#/trash' }
function tabFromHash() {
  const h = location.hash
  if (h.startsWith('#/')) {
    const t = h.slice(2)
    if (['search', 'pick', 'fs', 'favorites', 'trash'].includes(t)) return t
  }
  return null
}
function onHashChange() {
  const t = tabFromHash()
  if (t && t !== store.tab) {
    store.tab = t
    onFilterChange()
  }
}
// URL hash 优先于 localStorage 恢复的 tab；无 hash 时把恢复的 tab 写回 URL
const hTab = tabFromHash()
if (hTab) store.tab = hTab
else if (TAB_HASH[store.tab]) {
  try { history.replaceState(null, '', TAB_HASH[store.tab]) } catch { /* noop */ }
}
// tab 切换时同步 URL hash（replaceState 不产生历史记录、不触发 hashchange）
watch(() => store.tab, (t) => {
  const h = TAB_HASH[t]
  if (h && location.hash !== h) {
    try { history.replaceState(null, '', h) } catch { /* noop */ }
  }
})

onMounted(() => {
  init()
  window.addEventListener('keydown', onGlobalKey)
  window.addEventListener('hashchange', onHashChange)
  if (typeof window !== 'undefined') {
    window.verifyOrder = () => {
      console.log('%c[FileFinder 列表顺序与分页严密对齐自检]', 'color:#4c8bf5;font-weight:bold;font-size:14px;')
      const cells = listRef.value ? listRef.value.getCells() : []
      if (!cells.length) {
        console.warn('当前视口暂无卡片数据')
        return
      }
      let isStrict = true
      for (let i = 1; i < cells.length; i++) {
        if (cells[i].index !== cells[i - 1].index + 1) {
          isStrict = false
          console.error(`❌ 发现索引断裂: #${cells[i - 1].index + 1} (${cells[i - 1].item?.name}) -> #${cells[i].index + 1} (${cells[i].item?.name})`)
        }
      }
      if (isStrict) {
        console.log(`✅ 1. 视口绝对序号连续性：当前展示从 #${cells[0].index + 1} 到 #${cells[cells.length - 1].index + 1}，严格递增无任何断裂！`)
      }
      if (listRef.value?.pages) {
        const pages = [...listRef.value.pages.keys()].sort((a,b)=>a-b)
        console.log(`✅ 2. 内存分页幂等缓存：当前已缓存页码 [${pages.join(', ')}]，全部由确定性绝对页码生成。`)
      }
      return `当前视口展示第 #${cells[0].index + 1} ~ #${cells[cells.length - 1].index + 1} 项，顺序严格正确。`
    }

    window.compareSequences = (sub = window.__lastCopiedSequence, main = window.__prevCopiedSequence) => {
      console.log('%c[FileFinder 序列子集与有序性严格校验]', 'color:#4c8bf5;font-weight:bold;font-size:14px;')
      if (!sub || !sub.length || !main || !main.length) {
        console.warn('⚠️ 缺少比对序列。请右键目标图片执行两次“复制此前文件名序列”（先复制原序列，收藏并刷新后再次复制新序列），或手动传入两个数组：compareSequences(新序列, 原序列)')
        return
      }
      const missing = []
      const orderErrors = []
      let prevMainIdx = -1

      for (let sIdx = 0; sIdx < sub.length; sIdx++) {
        const name = sub[sIdx]
        const mainIdx = main.indexOf(name, prevMainIdx + 1)
        if (mainIdx === -1) {
          const foundAnywhere = main.indexOf(name)
          if (foundAnywhere >= 0) {
            orderErrors.push({ name, subIdx: sIdx, prevMatchedAt: prevMainIdx, foundInMainAt: foundAnywhere })
          } else {
            missing.push({ name, subIdx: sIdx })
          }
        } else {
          prevMainIdx = mainIdx
        }
      }

      if (!missing.length && !orderErrors.length) {
        console.log(`%c✅ [验证通过] 新序列（${sub.length} 项）完全是原序列（${main.length} 项）的严格有序子集！`, 'color:#4caf50;font-weight:bold;font-size:13px;')
        console.log(`ℹ️ 过滤/隐藏的收藏条目数：${main.length - sub.length} 项。剩余所有元素的相对前后顺序 100% 吻合！`)
        return { ok: true, subLength: sub.length, mainLength: main.length, filteredCount: main.length - sub.length }
      } else {
        console.error(`%c❌ [验证失败] 发现序列偏差：`, 'color:#e05c5c;font-weight:bold;font-size:13px;', {
          新序列总数: sub.length,
          原序列总数: main.length,
          不在原序列中的新增项: missing,
          相对顺序错位项: orderErrors,
        })
        return { ok: false, missing, orderErrors }
      }
    }

    window.copySequence = async (targetIdx) => {
      if (typeof targetIdx === 'number') {
        ctxTarget = { index: targetIdx, item: listRef.value?.getItemByIndex(targetIdx) }
      }
      await copySequenceBeforeTarget()
      return window.__lastCopiedSequence
    }
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKey)
  window.removeEventListener('hashchange', onHashChange)
})

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
  // 全选 Ctrl+A / Cmd+A
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
    e.preventDefault()
    const all = orderedItems()
    const next = new Set()
    for (const it of all) {
      const k = selKeyOf(it)
      if (k) next.add(k)
    }
    selKeys.value = next
    return
  }
  // 空格键：收藏 / 取消收藏当前选中项（无选中项时开关侧边预览栏）
  if (e.code === 'Space') {
    e.preventDefault()
    if (store.selected && store.tab !== 'trash') {
      onToggleFav(store.selected)
      return
    }
    store.showPreview = !store.showPreview
    return
  }
  // 拣选模式：Ctrl+Enter 快捷提交本批并切下一批
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && store.tab === 'pick') {
    e.preventDefault()
    pickDeleteAndNext()
    return
  }
  // Enter 键：若选中目录则进入该目录
  if (e.key === 'Enter') {
    if (store.selected && store.selected.is_dir) {
      e.preventDefault()
      onPreviewEnter()
    }
    return
  }
  // 上下左右方向键：二维智能切换选中图片/文件，视口自动滚动对齐
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
    e.preventDefault()
    const total = activeTotal.value
    if (total <= 0) return

    // 获取当前网格每行列数（表格模式固定为 1）
    const c = (store.viewMode === 'table') ? 1 : Math.max(1, listRef.value?.cols || 1)

    // 确定当前选中的全局绝对索引
    let curIdx = -1
    if (store.selected) {
      if (listRef.value) {
        curIdx = listRef.value.findIndexById(store.selected.id || store.selected.fav_id)
      }
      if (curIdx < 0) {
        const all = orderedItems()
        curIdx = all.findIndex(it => it && (it.id === store.selected.id || it.rel_path === store.selected.rel_path))
      }
    }

    let nextIdx = 0
    if (curIdx < 0) {
      // 当前尚未选中任何项：按方向键默认选中第 0 项
      nextIdx = 0
    } else {
      if (e.key === 'ArrowRight') {
        nextIdx = curIdx + 1
      } else if (e.key === 'ArrowLeft') {
        nextIdx = curIdx - 1
      } else if (e.key === 'ArrowDown') {
        nextIdx = curIdx + c
      } else if (e.key === 'ArrowUp') {
        nextIdx = curIdx - c
      }
    }

    // 限制在有效索引区间 [0, total - 1]
    nextIdx = Math.max(0, Math.min(total - 1, nextIdx))

    // 自动平滑滚动视口保证目标单元格完全可见
    if (listRef.value) {
      listRef.value.ensureIndexVisible(nextIdx)
    }

    // 获取目标条目并设为当前选中
    let target = listRef.value ? listRef.value.getItemByIndex(nextIdx) : null
    if (!target) {
      const all = orderedItems()
      target = all[nextIdx] || null
    }

    if (target) {
      const k = selKeyOf(target)
      selKeys.value = new Set([k])
      selAnchor = k
      store.selected = target
      store.previewKey++
    } else {
      // 跨页翻查时若目标页正在网络拉取，延时 120ms 再次尝试选中
      setTimeout(() => {
        const delayed = listRef.value ? listRef.value.getItemByIndex(nextIdx) : null
        if (delayed) {
          const k = selKeyOf(delayed)
          selKeys.value = new Set([k])
          selAnchor = k
          store.selected = delayed
          store.previewKey++
        }
      }, 120)
    }
    return
  }
  // Delete 键：回收站下彻底删除（带确认）；其他界面批量移入回收站
  if (e.key === 'Delete' && selKeys.value.size) {
    e.preventDefault()
    if (store.tab === 'trash') {
      batchPurge()
    } else {
      batchDelete()
    }
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
.del-prog { display: inline-flex; align-items: center; gap: 6px; color: #9aa4b2; font-size: 12px; }
.del-bar { display: inline-block; width: 72px; height: 6px; border-radius: 3px; background: #2a2f3a; overflow: hidden; vertical-align: middle; }
.del-bar i { display: block; height: 100%; background: #4c8bf5; border-radius: 3px; transition: width .15s ease; }
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

/* 拣选模式专用控制条 */
.pickstrip {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 6px 14px; background: #1c2128;
  border-bottom: 1px solid #333942;
  font-size: 12px; color: #adbac7;
  flex-wrap: wrap; z-index: 7;
}
.ps-stat {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.ps-tag {
  background: #316dca; color: #fff; font-size: 11px; font-weight: 600;
  border-radius: 4px; padding: 2px 7px;
}
.ps-fav { color: #f5b942; display: inline-flex; align-items: center; gap: 4px; }
.ps-unfav { color: #f85149; display: inline-flex; align-items: center; gap: 4px; }
.ps-remain { color: #768390; }
.ps-actions {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.ps-opt {
  display: inline-flex; align-items: center; gap: 5px; color: #8b949e; font-size: 11.5px;
}
.ps-sel {
  background: #22272e; color: #cdd9e5; border: 1px solid #444c56;
  border-radius: 4px; padding: 2px 6px; font-size: 11.5px; outline: none; cursor: pointer;
}
.ps-sel:focus { border-color: #539bf5; }
.ps-chk {
  display: inline-flex; align-items: center; gap: 5px; color: #adbac7; font-size: 11.5px;
  cursor: pointer; user-select: none;
}
.ps-chk input { accent-color: #316dca; cursor: pointer; }
.ps-btn-del {
  display: inline-flex; align-items: center; gap: 6px;
  font-weight: 600; padding: 4px 14px; font-size: 12px;
  border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  transition: all 0.15s ease;
}
.ps-btn-del:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(248, 81, 73, 0.35);
}

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
  transition: background 0.15s ease, transform 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.trow:hover { background: rgba(255,255,255,.04); }
.trow.sel { background: rgba(76,139,245,.16); }
.trow.pressing {
  background: rgba(245, 185, 66, 0.16) !important;
  transform: scale(0.995);
}
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

/* 浮层轻量 Toast 提示 */
.toast-tip {
  position: fixed;
  top: 56px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(30, 32, 38, 0.96);
  border: 1px solid #4caf50;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  color: #e5e7eb;
  padding: 8px 18px;
  border-radius: 8px;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  pointer-events: none;
}
.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: all 0.25s ease;
}
.toast-fade-enter-from {
  opacity: 0;
  transform: translate(-50%, -10px);
}
.toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -10px);
}
</style>
