/** 扩展名 → 预览类型 / 图标 / 颜色（与后端 preview_logic 保持一致） */

const TEXT_EXTS = new Set([
  'txt', 'md', 'markdown', 'log', 'json', 'yaml', 'yml', 'ini', 'conf', 'cfg',
  'xml', 'csv', 'html', 'htm', 'css', 'scss', 'less', 'js', 'mjs', 'cjs', 'ts',
  'jsx', 'tsx', 'py', 'pyw', 'java', 'c', 'cpp', 'cc', 'h', 'hpp', 'cs', 'go',
  'rs', 'rb', 'php', 'sql', 'sh', 'bash', 'bat', 'cmd', 'ps1', 'toml', 'properties',
  'sln', 'csproj', 'vcxproj', 'gradle', 'makefile', 'dockerfile', 'env', 'gitignore',
  'xaml', 'asm', 'vue', 'svelte', 'ipynb', 'diff', 'patch',
])
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico', 'avif', 'tif', 'tiff'])
const VIDEO_EXTS = new Set([
  'mp4', 'mkv', 'webm', 'mov', 'avi', 'flv', 'wmv', 'm4v', 'mpg', 'mpeg', '3gp',
  'ts', 'm2ts', 'ogv', 'rmvb',
])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac', 'wma'])
const ARCHIVE_EXTS = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'iso', 'dmg', 'img'])
const APP_EXTS = new Set(['exe', 'msi', 'dll', 'so', 'dylib', 'bat', 'cmd', 'sh', 'apk', 'app'])
const CODE_EXTS = new Set([
  'js', 'ts', 'jsx', 'tsx', 'py', 'java', 'c', 'cpp', 'cc', 'h', 'hpp', 'cs', 'go',
  'rs', 'rb', 'php', 'sql', 'sh', 'css', 'html', 'vue', 'svelte',
])
const DB_EXTS = new Set(['db', 'sqlite', 'sqlite3', 'dat'])

/** 预览类型: text | image | video | audio | archive | app | code | db | other */
export function classifyExt(ext) {
  const e = (ext || '').toLowerCase()
  if (IMAGE_EXTS.has(e)) return 'image'
  if (VIDEO_EXTS.has(e)) return 'video'
  if (AUDIO_EXTS.has(e)) return 'audio'
  if (ARCHIVE_EXTS.has(e)) return 'archive'
  if (APP_EXTS.has(e)) return 'app'
  if (DB_EXTS.has(e)) return 'db'
  if (TEXT_EXTS.has(e)) return 'text'
  if (CODE_EXTS.has(e)) return 'code'
  return 'other'
}

/** 文件图标名（映射到 icons.js） */
export function fileIcon(item) {
  if (item.is_dir) return 'folder'
  switch (classifyExt(item.ext)) {
    case 'image': return 'image'
    case 'video': return 'video'
    case 'audio': return 'audio'
    case 'archive': return 'archive'
    case 'app': return 'app'
    case 'db': return 'db'
    case 'text':
    case 'code': return 'code'
    default: return 'file'
  }
}

/** 图标主色 */
export function fileColor(item) {
  if (item.is_dir) return '#e8c468'
  switch (classifyExt(item.ext)) {
    case 'image': return '#4caf50'
    case 'video': return '#e05cb5'
    case 'audio': return '#7e57c2'
    case 'archive': return '#e5a33d'
    case 'app': return '#e05c5c'
    case 'db': return '#4c8bf5'
    case 'text': return '#8ab4f8'
    case 'code': return '#4caf9e'
    default: return '#9aa0a6'
  }
}

/** 后端是否支持预览 */
export function previewable(item) {
  const k = classifyExt(item.ext)
  return k === 'text' || k === 'code' || k === 'image' || k === 'video'
}
