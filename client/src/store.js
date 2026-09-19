/** 全局状态（轻量单例，避免重型状态库带来的额外开销） */
import { reactive } from 'vue'

export const VIEW_MODES = {
  small: { colWidth: 148, rowHeight: 128, thumb: 96 },
  medium: { colWidth: 216, rowHeight: 188, thumb: 160 },
  large: { colWidth: 316, rowHeight: 264, thumb: 240 },
}

export const store = reactive({
  tab: 'search',            // 'search' | 'favorites' | 'fs'（文件系统浏览）
  viewMode: 'medium',       // 'small' | 'medium' | 'large' | 'table'
  q: '',
  regex: false,             // 正则表达式搜索开关
  rootId: null,             // null = 全部根
  ext: '',                  // '' = 全部扩展名
  favOnly: false,
  sort: 'name',             // name | size | mtime
  order: 'asc',             // asc | desc

  roots: [],                // 扫描根列表
  stats: null,              // 全局统计
  selected: null,           // 当前选中项（搜索项/收藏项/浏览项）
  searchTotal: 0,
  favTotal: 0,
  fsTotal: 0,               // 文件系统当前目录条目数
  showPreview: true,
  previewKey: 0,            // 选中项变化时自增，驱动预览面板刷新
  previewWidth: 380,        // 预览面板宽度（可拖拽拉伸）
  tasks: [],                // 活跃任务（含进度）

  // 文件系统浏览（类资源管理器）
  fsRoot: null,             // 当前浏览根 { id, path, display_name }
  fsRel: '',                // 当前浏览目录（根内相对路径，'' = 根本身）

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

export const viewCfg = () => VIEW_MODES[store.viewMode] || VIEW_MODES.medium
