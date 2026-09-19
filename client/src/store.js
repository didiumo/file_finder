/** 全局状态（轻量单例，避免重型状态库带来的额外开销） */
import { reactive, watch } from 'vue'

export const VIEW_MODES = {
  small: { colWidth: 148, rowHeight: 128, thumb: 96 },
  medium: { colWidth: 216, rowHeight: 188, thumb: 160 },
  large: { colWidth: 316, rowHeight: 264, thumb: 240 },
}

/** 过滤条件持久化键：tab / 视图 / 搜索词 / 类型 / 排序等，刷新后恢复 */
const FILTER_KEY = 'ff_filters'
const TABS = ['search', 'fs', 'favorites', 'trash']
const VIEWS = ['small', 'medium', 'large', 'table']
function loadSaved() {
  try {
    const o = JSON.parse(localStorage.getItem(FILTER_KEY) || '{}')
    return o && typeof o === 'object' ? o : {}
  } catch { return {} }
}
const saved = loadSaved()

export const store = reactive({
  tab: TABS.includes(saved.tab) ? saved.tab : 'search',   // 'search' | 'favorites' | 'fs'（文件系统浏览） | 'trash'（回收站）
  viewMode: VIEWS.includes(saved.viewMode) ? saved.viewMode : 'medium',  // 'small' | 'medium' | 'large' | 'table'
  q: typeof saved.q === 'string' ? saved.q : '',
  regex: !!saved.regex,     // 正则表达式搜索开关
  rootId: saved.rootId != null ? saved.rootId : null,     // null = 全部根
  ext: typeof saved.ext === 'string' ? saved.ext : '',    // '' = 全部扩展名
  favOnly: !!saved.favOnly,
  // 隐藏已收藏（搜索时排除已收藏项；状态持久化，刷新后仍生效）
  hideFav: saved.hideFav !== undefined ? !!saved.hideFav
    : (() => { try { return localStorage.getItem('ff_hide_fav') === '1' } catch { return false } })(),
  sort: typeof saved.sort === 'string' ? saved.sort : 'name',   // name | size | mtime
  order: saved.order === 'desc' ? 'desc' : 'asc',               // asc | desc

  roots: [],                // 扫描根列表
  stats: null,              // 全局统计
  selected: null,           // 当前选中项（搜索项/收藏项/浏览项）
  searchTotal: 0,
  favTotal: 0,
  fsTotal: 0,               // 文件系统当前目录条目数
  trashTotal: 0,            // 回收站条目数
  showPreview: true,
  previewKey: 0,            // 选中项变化时自增，驱动预览面板刷新
  previewWidth: 380,        // 预览面板宽度（可拖拽拉伸）
  tasks: [],                // 活跃任务（含进度）

  // 文件系统浏览（类资源管理器）
  fsRoot: null,             // 当前浏览根 { id, path, display_name }
  fsRel: typeof saved.fsRel === 'string' ? saved.fsRel : '',   // 当前浏览目录（根内相对路径，'' = 根本身）

  // “在此目录搜索”范围（搜索 Tab 生效）：{ root_id, prefix, label }
  searchScope: null,
})

/** 表格视图列宽（px，可拖拽调整，localStorage 持久化） */
const savedCols = (() => {
  try { return JSON.parse(localStorage.getItem('ff_tableCols') || 'null') } catch { return null }
})()
export const tableCols = reactive({
  name: 260, ext: 70, size: 90, date: 130, path: 200,
  ...(savedCols && typeof savedCols === 'object' ? savedCols : {}),
})
export function saveTableCols() {
  try { localStorage.setItem('ff_tableCols', JSON.stringify({ ...tableCols })) } catch { /* noop */ }
}

export function setHideFav(v) {
  store.hideFav = !!v
  try { localStorage.setItem('ff_hide_fav', store.hideFav ? '1' : '0') } catch { /* noop */ }
}

/** 过滤条件与浏览位置统一持久化（含 fsRootId 供 App 恢复浏览根） */
export function persistFilters() {
  try {
    localStorage.setItem(FILTER_KEY, JSON.stringify({
      tab: store.tab, viewMode: store.viewMode, q: store.q, regex: store.regex,
      rootId: store.rootId, ext: store.ext, favOnly: store.favOnly, hideFav: store.hideFav,
      sort: store.sort, order: store.order,
      fsRootId: store.fsRoot ? store.fsRoot.id : null, fsRel: store.fsRel,
    }))
  } catch { /* noop */ }
}
watch(() => [store.tab, store.viewMode, store.q, store.regex, store.rootId, store.ext,
             store.favOnly, store.hideFav, store.sort, store.order,
             store.fsRoot ? store.fsRoot.id : null, store.fsRel],
  () => persistFilters())

export const viewCfg = () => VIEW_MODES[store.viewMode] || VIEW_MODES.medium
