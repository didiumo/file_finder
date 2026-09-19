<!-- 顶部工具栏：搜索 / 过滤 / 排序 / 视图切换 / 标签页 -->
<template>
  <header class="topbar">
    <div class="tabs">
      <button class="tab" :class="{ on: store.tab === 'search' }" @click="switchTab('search')">
        <Icon name="search" :size="14" /> 搜索
      </button>
      <button class="tab" :class="{ on: store.tab === 'fs' }" @click="switchTab('fs')">
        <Icon name="folder" :size="14" /> 文件系统
      </button>
      <button class="tab" :class="{ on: store.tab === 'favorites' }" @click="switchTab('favorites')">
        <Icon name="star" :size="14" /> 收藏
        <span v-if="store.favTotal > 0" class="cnt">{{ store.favTotal }}</span>
      </button>
    </div>

    <div class="search-wrap">
      <Icon name="search" :size="15" class="s-ic" />
      <input
        ref="qInput"
        v-model="qText"
        class="q-input"
        :class="{ rx: store.regex }"
        type="text"
        :placeholder="searchPlaceholder"
        spellcheck="false"
        :disabled="store.tab === 'fs'"
        @input="onInput"
        @keydown.enter.prevent="onEnter"
      />
      <button
        class="rx-btn"
        :class="{ on: store.regex }"
        title="正则匹配（输入正则表达式，如 .*\\.(png|jpg)$）"
        @click="toggleRegex"
      >
        <span class="rx-dot">.*</span>
      </button>
      <button v-if="qText" class="clear" @click="clearQ"><Icon name="x" :size="13" /></button>
    </div>

    <div v-if="store.searchScope" class="scope-chip" :title="`在 ${store.searchScope.label} 内搜索`">
      <Icon name="folder" :size="12" />
      <span class="scope-path">{{ store.searchScope.label }}</span>
      <button class="scope-x" title="清除范围，恢复全局搜索" @click="clearScope"><Icon name="x" :size="11" /></button>
    </div>

    <div class="filters" v-if="store.tab !== 'fs'">
      <select v-model="store.rootId" class="sel" title="扫描根" @change="onFilterChange">
        <option :value="null">全部根目录</option>
        <option v-for="r in store.roots" :key="r.id" :value="r.id" :title="r.path">{{ r.display_name || r.path }}</option>
      </select>

      <select v-model="store.ext" class="sel" title="扩展名过滤" @change="onFilterChange">
        <option value="">全部类型</option>
        <optgroup label="媒体">
          <option value="png,jpg,jpeg,gif,webp,bmp,svg,ico,avif,tif,tiff">图片</option>
          <option value="mp4,mkv,webm,mov,avi,flv,wmv,m4v,mpg,mpeg,3gp,ts,m2ts,ogv,rmvb">视频</option>
          <option value="mp3,wav,flac,ogg,m4a,aac,wma">音频</option>
        </optgroup>
        <optgroup label="文本">
          <option value="txt,md,markdown">文本/文档</option>
          <option value="json">JSON</option>
          <option value="log">日志</option>
          <option value="py,js,ts,go,java,c,cpp,h,hpp,cs,rs,php,sql,html,css">代码</option>
          <option value="csv,xml,yaml,yml,ini,conf,toml">配置/数据</option>
        </optgroup>
        <optgroup label="其他">
          <option value="zip,rar,7z,tar,gz,bz2,xz,iso,dmg,img">压缩包/镜像</option>
          <option value="db,sqlite,sqlite3,dat">数据库</option>
          <option value="exe,msi,dll,so,dylib">程序/库</option>
        </optgroup>
      </select>

      <select v-model="store.sort" class="sel" title="排序字段" @change="onFilterChange">
        <option value="name">按名称</option>
        <option value="size">按大小</option>
        <option value="mtime">按修改时间</option>
      </select>
      <button class="ord-btn" :title="store.order === 'asc' ? '升序' : '降序'" @click="toggleOrder">
        {{ store.order === 'asc' ? '↑' : '↓' }}
      </button>

      <label class="chk" title="仅显示收藏">
        <input type="checkbox" v-model="store.favOnly" @change="onFilterChange" />
        <Icon name="star" :size="12" /> 仅收藏
      </label>
    </div>

    <div class="view-actions">
      <div class="view-group" title="视图模式">
        <button v-for="m in viewModes" :key="m.key" class="vm" :class="{ on: store.viewMode === m.key }"
                :title="m.label" @click="setView(m.key)">
          <Icon :name="m.icon" :size="15" />
        </button>
      </div>
      <button class="icon-btn" title="刷新（重新拉取首页）" @click="$emit('refresh')"><Icon name="refresh" :size="15" /></button>
      <button class="icon-btn" title="扫描根目录管理" @click="$emit('open-roots')"><Icon name="settings" :size="15" /></button>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import Icon from './Icon.vue'
import { store } from '../store'

const emit = defineEmits(['filter-change', 'refresh', 'open-roots'])

const qText = ref('')
const qInput = ref(null)
let debounce = 0
// 外部清空/切换搜索词（如“在此目录搜索”）时同步输入框
watch(() => store.q, (v) => { qText.value = v || '' })
const viewModes = [
  { key: 'small', label: '小缩略图', icon: 'grid' },
  { key: 'medium', label: '中缩略图', icon: 'grid' },
  { key: 'large', label: '大缩略图', icon: 'grid' },
  { key: 'table', label: '表格', icon: 'table' },
]

const searchPlaceholder = computed(() => {
  if (store.regex) return '正则匹配文件名 / 路径（如 .*\\.(png|jpg)$）'
  if (store.searchScope) return `在「${store.searchScope.label}」内搜索（回车即时搜索）`
  return '搜索文件名 / 路径（回车即时搜索）'
})

function onInput() {
  clearTimeout(debounce)
  debounce = setTimeout(() => {
    store.q = qText.value.trim()
    emit('filter-change')
  }, 150)
}
function onEnter() {
  clearTimeout(debounce)
  store.q = qText.value.trim()
  emit('filter-change')
}
function clearQ() {
  qText.value = ''
  store.q = ''
  emit('filter-change')
  qInput.value && qInput.value.focus()
}
function toggleRegex() {
  store.regex = !store.regex
  emit('filter-change')
}
function clearScope() {
  store.searchScope = null
  emit('filter-change')
}
function onFilterChange() { emit('filter-change') }
function toggleOrder() {
  store.order = store.order === 'asc' ? 'desc' : 'asc'
  emit('filter-change')
}
function setView(m) {
  store.viewMode = m
  emit('filter-change')
}
function switchTab(t) {
  store.tab = t
  store.selected = null
  store.previewKey++
  emit('filter-change')
}
</script>

<style scoped>
.topbar {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: #1a1c1f; border-bottom: 1px solid #2e3137;
  flex-wrap: wrap;
}
.tabs { display: flex; gap: 2px; }
.tab {
  display: flex; align-items: center; gap: 5px;
  background: none; border: none; color: #8b919a; cursor: pointer;
  padding: 6px 10px; border-radius: 6px; font-size: 13px;
}
.tab:hover { background: rgba(255,255,255,.05); color: #e3e6eb; }
.tab.on { background: rgba(76,139,245,.15); color: #6ab0ff; }
.cnt {
  background: #3d78e6; color: #fff; border-radius: 9px;
  font-size: 10px; padding: 0 6px; line-height: 16px;
}
.search-wrap {
  flex: 1; min-width: 220px; max-width: 520px; position: relative; display: flex; align-items: center;
}
.s-ic { position: absolute; left: 10px; color: #6c727c; pointer-events: none; }
.q-input {
  width: 100%; background: #26282d; border: 1px solid #33363d; color: #e3e6eb;
  border-radius: 8px; padding: 7px 62px 7px 32px; font-size: 13px; outline: none;
}
.q-input:focus { border-color: #3d78e6; }
.q-input.rx { border-color: #8a5ce6; }
.q-input:disabled { opacity: .5; }
.rx-btn {
  position: absolute; right: 30px; background: none; border: none; cursor: pointer;
  padding: 3px 5px; border-radius: 5px; color: #6c727c; display: flex; align-items: center;
}
.rx-btn:hover { color: #c9cdd4; }
.rx-btn.on { background: rgba(138,92,230,.2); color: #b18cf0; }
.rx-dot { font-family: Consolas, monospace; font-size: 12px; font-weight: 700; }
.clear {
  position: absolute; right: 6px; background: none; border: none; color: #6c727c;
  cursor: pointer; padding: 3px; display: flex; border-radius: 4px;
}
.clear:hover { color: #e3e6eb; }
.scope-chip {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(76,139,245,.12); border: 1px solid #3d556e; color: #6ab0ff;
  border-radius: 7px; padding: 4px 8px; font-size: 12px; max-width: 320px;
}
.scope-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scope-x { background: none; border: none; color: inherit; cursor: pointer; padding: 1px; display: flex; opacity: .7; }
.scope-x:hover { opacity: 1; }
.filters { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sel {
  background: #26282d; border: 1px solid #33363d; color: #c9cdd4;
  border-radius: 7px; padding: 6px 8px; font-size: 12px; outline: none;
  max-width: 150px;
}
.sel option { background: #26282d; }
.ord-btn {
  background: #26282d; border: 1px solid #33363d; color: #c9cdd4;
  border-radius: 7px; padding: 4px 9px; font-size: 13px; cursor: pointer;
}
.ord-btn:hover { color: #fff; }
.chk {
  display: inline-flex; align-items: center; gap: 4px;
  color: #8b919a; font-size: 12px; cursor: pointer; padding: 4px 6px;
  border-radius: 6px; user-select: none;
}
.chk:hover { background: rgba(255,255,255,.05); color: #e3e6eb; }
.chk input { accent-color: #3d78e6; }
.view-actions { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.view-group { display: flex; background: #26282d; border: 1px solid #33363d; border-radius: 7px; overflow: hidden; }
.vm {
  background: none; border: none; color: #8b919a; cursor: pointer;
  padding: 5px 8px; display: flex;
}
.vm + .vm { border-left: 1px solid #33363d; }
.vm:hover { color: #e3e6eb; }
.vm.on { background: rgba(76,139,245,.2); color: #6ab0ff; }
.icon-btn {
  background: #26282d; border: 1px solid #33363d; color: #9aa0a6;
  border-radius: 7px; padding: 5px 8px; cursor: pointer; display: flex;
}
.icon-btn:hover { color: #e3e6eb; }
</style>
