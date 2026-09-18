<!-- 扫描根管理弹窗 -->
<template>
  <div v-if="open" class="overlay" @click.self="close">
    <div class="dialog">
      <div class="d-head">
        <span>扫描根目录</span>
        <button class="x" @click="close"><Icon name="x" :size="15" /></button>
      </div>
      <div class="d-body">
        <div class="add-row">
          <input
            v-model="newPath" class="add-input" placeholder="输入网络共享路径，如 \\\\server\\share\\folder"
            spellcheck="false" @keyup.enter="addRoot"
          />
          <button class="pprim" @click="addRoot" :disabled="busy"><Icon name="folderPlus" :size="14" /> 添加</button>
        </div>
        <div class="root-list">
          <div v-for="r in roots" :key="r.id" class="root-item">
            <div class="r-main">
              <div class="r-path" :title="r.path">
                <span class="dot" :class="{ off: !r.enabled }"></span>
                {{ r.path }}
              </div>
              <div class="r-sub">
                <span>{{ r.file_count || 0 }} 文件</span>
                <span>{{ r.dir_count || 0 }} 目录</span>
                <span v-if="r.last_scan_at">{{ formatDate(r.last_scan_at) }} 扫描</span>
                <span v-else class="never">未扫描</span>
                <span v-if="r.last_scan_status && r.last_scan_status !== 'completed'" :class="'st-' + r.last_scan_status">
                  {{ r.last_scan_status }}
                </span>
              </div>
            </div>
            <div class="r-actions">
              <select v-model="scanMode[r.id]" class="mini-sel" title="扫描模式">
                <option value="incremental">增量</option>
                <option value="full">全量</option>
              </select>
              <button class="mini" :disabled="!r.enabled" @click="scan(r)"><Icon name="zap" :size="13" /> 扫描</button>
              <button class="mini" @click="toggleRoot(r)">{{ r.enabled ? '停用' : '启用' }}</button>
              <button class="mini danger" @click="removeRoot(r)"><Icon name="trash" :size="13" /></button>
            </div>
          </div>
        </div>
        <p class="tip">提示：停用根目录后搜索将不包含其内容；删除根目录仅移除索引记录，不会删除磁盘文件。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Icon from './Icon.vue'
import { store } from '../store'
import { apiRoots } from '../api'
import { formatDate } from '../utils/format'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close', 'task'])

const newPath = ref('')
const busy = ref(false)
const scanMode = ref({})

const roots = computed(() => store.roots)

async function refresh() {
  const r = await apiRoots.list()
  store.roots = r.data.roots
}
async function addRoot() {
  const p = newPath.value.trim()
  if (!p || busy.value) return
  busy.value = true
  try {
    const r = await apiRoots.add(p)
    newPath.value = ''
    await refresh()
    if (r.data.id) {
      const t = await apiRoots.scan(r.data.id, 'incremental')
      if (t.data?.task_id) emit('task', t.data.task_id)
    }
  } catch (e) { alert('添加失败: ' + e.message) } finally { busy.value = false }
}
async function scan(r) {
  try {
    const t = await apiRoots.scan(r.id, scanMode.value[r.id] || 'incremental')
    if (t.data?.task_id) emit('task', t.data.task_id)
    // 延迟刷新根列表以更新状态
    setTimeout(refresh, 3000)
  } catch (e) { alert('扫描失败: ' + e.message) }
}
async function toggleRoot(r) {
  try {
    await apiRoots.setEnabled(r.id, !r.enabled)
    await refresh()
  } catch (e) { alert('操作失败: ' + e.message) }
}
async function removeRoot(r) {
  if (!confirm(`确定移除扫描根「${r.path}」？\n仅移除索引记录，不删除磁盘文件。`)) return
  try {
    await apiRoots.remove(r.id)
    if (store.rootId === r.id) store.rootId = null
    await refresh()
  } catch (e) { alert('移除失败: ' + e.message) }
}
function close() {
  emit('close')
  store.selected = null
  store.previewKey++
}
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.dialog {
  width: 720px; max-width: 94vw; max-height: 82vh;
  background: #222428; border: 1px solid #33363d; border-radius: 12px;
  display: flex; flex-direction: column; overflow: hidden;
}
.d-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #2e3137; color: #e3e6eb; font-size: 14px; font-weight: 600;
}
.x { background: none; border: none; color: #8b919a; cursor: pointer; padding: 4px; border-radius: 6px; display: flex; }
.x:hover { color: #fff; background: rgba(255,255,255,.08); }
.d-body { padding: 14px 16px; overflow: auto; }
.add-row { display: flex; gap: 8px; margin-bottom: 12px; }
.add-input {
  flex: 1; background: #1a1c1f; border: 1px solid #33363d; color: #e3e6eb;
  border-radius: 7px; padding: 8px 10px; font-size: 12.5px; outline: none;
}
.add-input:focus { border-color: #3d78e6; }
.pprim {
  display: inline-flex; align-items: center; gap: 5px;
  background: #3d78e6; color: #fff; border: none; padding: 8px 14px;
  border-radius: 7px; font-size: 12.5px; cursor: pointer;
}
.pprim:hover { background: #4c8bf5; }
.pprim:disabled { opacity: .5; cursor: default; }
.root-list { display: flex; flex-direction: column; gap: 8px; }
.root-item {
  background: #1f2125; border: 1px solid #2e3137; border-radius: 9px;
  padding: 10px 12px; display: flex; align-items: center; gap: 10px;
}
.r-main { flex: 1; min-width: 0; }
.r-path {
  font-size: 13px; color: #d5d9e0; font-family: Consolas, monospace;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  display: flex; align-items: center; gap: 6px;
}
.dot { width: 8px; height: 8px; border-radius: 50%; background: #4caf50; flex-shrink: 0; }
.dot.off { background: #6c727c; }
.r-sub { display: flex; gap: 12px; margin-top: 4px; font-size: 11px; color: #8b919a; }
.never { color: #d9a53f; }
.st-failed { color: #e05c5c; }
.st-running { color: #6ab0ff; }
.r-actions { display: flex; gap: 5px; align-items: center; flex-shrink: 0; }
.mini-sel {
  background: #26282d; border: 1px solid #33363d; color: #c9cdd4;
  border-radius: 6px; padding: 4px 6px; font-size: 11px; outline: none;
}
.mini {
  background: #26282d; border: 1px solid #33363d; color: #c9cdd4;
  border-radius: 6px; padding: 5px 9px; font-size: 11.5px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
}
.mini:hover { color: #fff; border-color: #4a4f59; }
.mini.danger:hover { color: #e05c5c; border-color: #7a3b3b; }
.mini:disabled { opacity: .45; cursor: default; }
.tip { margin-top: 12px; font-size: 11px; color: #6c727c; }
</style>
