<!-- 侧边预览面板：文本 / Markdown / 图片 / 视频 -->
<template>
  <aside class="preview" :class="{ empty: !store.selected }">
    <template v-if="store.selected">
      <div class="pv-head">
        <div class="pv-name" :title="store.selected.rel_path">
          <Icon :name="iconName" :size="15" :style="{ color: itemColor }" />
          <span>{{ store.selected.name }}</span>
        </div>
        <div class="pv-actions">
          <button class="abtn" title="收藏/取消收藏" :class="{ on: store.selected.favorite || isFav }" @click="toggleFav">
            <Icon name="star" :size="15" />
          </button>
          <button class="abtn" title="复制路径" @click="copyPath"><Icon name="copy" :size="15" /></button>
          <button class="abtn" title="下载" @click="download"><Icon name="download" :size="15" /></button>
          <button class="abtn danger" title="删除文件" @click="removeFile"><Icon name="trash" :size="15" /></button>
          <button class="abtn" title="关闭预览" @click="store.showPreview = false; store.selected = null"><Icon name="x" :size="15" /></button>
        </div>
      </div>
      <div class="pv-meta">
        <span>{{ formatSize(item.size) }}</span>
        <span>{{ formatDate(item.mtime) }}</span>
        <span class="root">{{ item.root_name }}</span>
      </div>
      <div class="pv-body">
        <!-- 文件已丢失 -->
        <template v-if="!item.id">
          <div class="unsupported">
            <Icon name="warn" :size="52" style="color:#d9a53f" />
            <p>文件已丢失或不可访问</p>
            <p class="ext">索引记录仍在，可取消收藏</p>
          </div>
        </template>
        <!-- 文本 -->
        <template v-else-if="kind === 'text' || kind === 'code'">
          <div v-if="isMarkdown" class="md-body" v-html="mdHtml"></div>
          <pre v-else class="text-body"><code>{{ textContent }}</code></pre>
          <div v-if="truncated" class="trunc-tip">内容过长，已截断显示前 {{ formatSize(truncLen) }}</div>
        </template>
        <!-- 图片 -->
        <template v-else-if="kind === 'image'">
          <div class="img-wrap">
            <img v-if="!mediaFailed" :src="previewUrl" alt="" @error="mediaFailed = true" />
            <div v-else class="unsupported">
              <Icon name="warn" :size="52" style="color:#d9a53f" />
              <p>文件已丢失或不可访问</p>
              <p class="ext">缩略图/预览加载失败（{{ item.name }}）</p>
            </div>
          </div>
        </template>
        <!-- 视频 -->
        <template v-else-if="kind === 'video'">
          <video v-if="!mediaFailed" :src="previewUrl" controls autoplay playsinline class="video" @error="mediaFailed = true"></video>
          <div v-else class="unsupported">
            <Icon name="warn" :size="52" style="color:#d9a53f" />
            <p>文件已丢失或不可访问</p>
            <p class="ext">视频加载失败（{{ item.name }}）</p>
          </div>
        </template>
        <!-- 不支持 -->
        <template v-else>
          <div class="unsupported">
            <Icon :name="iconName" :size="56" :style="{ color: itemColor }" />
            <p>该类型暂不支持预览</p>
            <p class="ext">{{ item.ext || '未知类型' }}</p>
            <button class="pprim" @click="download"><Icon name="download" :size="14" /> 下载文件</button>
          </div>
        </template>
      </div>
      <div class="pv-path" :title="item.rel_path">{{ item.root_path }}\{{ item.rel_path }}</div>
    </template>
    <div v-else class="pv-placeholder">
      <Icon name="eye" :size="40" />
      <p>选择文件以预览</p>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { marked } from 'marked'
import Icon from './Icon.vue'
import { store } from '../store'
import { formatSize, formatDate } from '../utils/format'
import { classifyExt, fileIcon, fileColor, previewable } from '../utils/fileTypes'
import { apiFiles, apiFavorites, fetchTextPreview } from '../api'

const textContent = ref('')
const truncated = ref(false)
const truncLen = ref(0)
const isFav = ref(false)
const loading = ref(false)
const mediaFailed = ref(false)
let controller = null

const emit = defineEmits(['deleted'])

const item = computed(() => store.selected || {})
const kind = computed(() => classifyExt(item.value.ext))
const iconName = computed(() => fileIcon(item.value))
const itemColor = computed(() => fileColor(item.value))
const isMarkdown = computed(() => ['md', 'markdown'].includes((item.value.ext || '').toLowerCase()))
const mdHtml = computed(() => {
  try { return marked.parse(textContent.value || '') } catch { return textContent.value }
})
const previewUrl = computed(() => (item.value.id ? apiFiles.previewUrl(item.value.id) : ''))

watch(() => store.previewKey, async () => {
  const it = item.value
  if (!it || !it.id) return
  isFav.value = !!it.favorite
  mediaFailed.value = false
  const k = classifyExt(it.ext)
  loading.value = true
  textContent.value = ''
  truncated.value = false
  if (controller) controller.abort()
  controller = new AbortController()
  if (k === 'text' || k === 'code') {
    try {
      const t = await fetchTextPreview(it.id, controller.signal)
      textContent.value = t.content
      truncated.value = t.truncated
      truncLen.value = t.truncated ? Math.min(it.size || 0, 262144) : 0
    } catch (e) {
      if (e.name !== 'AbortError') textContent.value = `读取失败: ${e.message}`
    }
  }
  loading.value = false
})

async function toggleFav() {
  const it = item.value
  if (!it || !it.id) return
  let favorite
  if (it.fav_id && !it.file_id) {
    // 收藏视图且文件丢失：按收藏记录删除
    await apiFavorites.remove(it.fav_id)
    favorite = false
  } else {
    const r = await apiFavorites.toggle(it.id)
    favorite = r.data.favorite
  }
  it.favorite = favorite
  store.previewKey++
  emit('deleted') // 触发列表刷新（收藏状态变化）
}

async function copyPath() {
  try {
    await navigator.clipboard.writeText(item.value.root_path + '\\' + item.value.rel_path)
  } catch { /* noop */ }
}

function download() {
  if (!item.value.id) return
  const a = document.createElement('a')
  a.href = apiFiles.downloadUrl(item.value.id)
  a.download = item.value.name
  a.click()
}

async function removeFile() {
  const it = item.value
  if (!it || !it.id || it.is_dir) return
  if (!confirm(`确定删除文件「${it.name}」？\n${it.root_path}\\${it.rel_path}`)) return
  await apiFiles.remove(it.id)
  store.selected = null
  store.previewKey++
  emit('deleted')
}

onBeforeUnmount(() => { controller && controller.abort() })
</script>

<style scoped>
.preview {
  width: 380px;
  min-width: 380px;
  border-left: 1px solid #2e3137;
  background: #222428;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.preview.empty { align-items: center; justify-content: center; }
.pv-placeholder { color: #5c626d; text-align: center; }
.pv-placeholder p { margin-top: 10px; font-size: 13px; }
.pv-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px 6px; gap: 8px;
}
.pv-name { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #e3e6eb; min-width: 0; }
.pv-name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pv-actions { display: flex; gap: 2px; flex-shrink: 0; }
.abtn {
  background: none; border: none; color: #9aa0a6; cursor: pointer;
  padding: 5px; border-radius: 6px; display: flex;
}
.abtn:hover { background: rgba(255,255,255,.08); color: #e3e6eb; }
.abtn.on { color: #f5b942; }
.abtn.danger:hover { color: #e05c5c; }
.pv-meta { display: flex; gap: 10px; padding: 0 12px 8px; font-size: 11px; color: #8b919a; }
.pv-meta .root { color: #6c727c; }
.pv-body { flex: 1; min-height: 0; overflow: auto; padding: 0 12px 12px; }
.text-body {
  font-size: 12px; line-height: 1.6; color: #d5d9e0;
  background: #1a1c1f; padding: 10px; border-radius: 6px;
  white-space: pre-wrap; word-break: break-all; max-height: 100%;
  font-family: Consolas, 'Courier New', monospace;
}
.md-body { font-size: 13px; line-height: 1.7; color: #d5d9e0; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3) { color: #fff; margin: 14px 0 8px; }
.md-body :deep(p) { margin: 6px 0; }
.md-body :deep(code) { background: #2a2d33; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.md-body :deep(pre) { background: #1a1c1f; padding: 10px; border-radius: 6px; overflow: auto; }
.md-body :deep(pre code) { background: none; padding: 0; }
.md-body :deep(a) { color: #6ab0ff; }
.md-body :deep(img) { max-width: 100%; border-radius: 6px; }
.trunc-tip { margin-top: 8px; font-size: 11px; color: #d9a53f; }
.img-wrap { display: flex; align-items: center; justify-content: center; height: 100%; }
.img-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 6px; }
.video { width: 100%; max-height: 100%; border-radius: 6px; background: #000; }
.unsupported { text-align: center; color: #8b919a; padding-top: 40px; }
.unsupported p { margin: 10px 0 0; font-size: 13px; }
.unsupported .ext { font-size: 11px; color: #6c727c; }
.pprim {
  margin-top: 16px; display: inline-flex; align-items: center; gap: 6px;
  background: #3d78e6; color: #fff; border: none; padding: 7px 16px;
  border-radius: 6px; font-size: 12px; cursor: pointer;
}
.pprim:hover { background: #4c8bf5; }
.pv-path {
  padding: 6px 12px; font-size: 10.5px; color: #6c727c;
  border-top: 1px solid #2e3137; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; direction: rtl; text-align: left;
}
</style>
