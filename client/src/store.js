/** 全局状态（轻量单例，避免重型状态库带来的额外开销） */
import { reactive, ref } from 'vue'

export const VIEW_MODES = {
  small: { colWidth: 148, rowHeight: 128, thumb: 96 },
  medium: { colWidth: 216, rowHeight: 188, thumb: 160 },
  large: { colWidth: 316, rowHeight: 264, thumb: 240 },
}

export const store = reactive({
  tab: 'search',            // 'search' | 'favorites'
  viewMode: 'medium',       // 'small' | 'medium' | 'large' | 'table'
  q: '',
  rootId: null,             // null = 全部根
  ext: '',                  // '' = 全部扩展名
  favOnly: false,
  sort: 'name',             // name | size | mtime
  order: 'asc',             // asc | desc

  roots: [],                // 扫描根列表
  stats: null,              // 全局统计
  selected: null,           // 当前选中项（搜索项或收藏项）
  searchTotal: 0,
  favTotal: 0,
  showPreview: true,
  previewKey: 0,            // 选中项变化时自增，驱动预览面板刷新
  tasks: [],                // 活跃任务（含进度）
})

export const viewCfg = () => VIEW_MODES[store.viewMode] || VIEW_MODES.medium
