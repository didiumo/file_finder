<!-- 文件卡片（网格单元）：图片缩略图 / 类型图标 + 元信息 -->
<template>
  <div
    class="card"
    :class="[`m-${mode}`, { selected, missing: item?.exists_now === false }]"
    :title="item ? item.rel_path : ''"
    @click="onClick"
    @dblclick="onDblClick"
  >
    <div class="thumb">
      <template v-if="item">
        <img
          v-if="showThumb"
          :src="thumbUrl"
          loading="lazy"
          decoding="async"
          draggable="false"
          alt=""
          @error="imgError = true"
        />
        <Icon v-else :name="iconName" :size="iconSize" :style="{ color: item.is_dir ? '#e8c468' : fileColor(item) }" />
        <span v-if="isVideo" class="play-badge"><Icon name="play" :size="14" /></span>
        <span v-if="item.is_dir" class="dir-badge"><Icon name="folder" :size="14" /></span>
        <span v-if="item.favorite" class="fav-badge"><Icon name="star" :size="13" /></span>
        <span v-if="item.exists_now === false" class="missing-badge">丢失</span>
      </template>
      <div v-else class="skeleton"></div>
    </div>
    <div class="meta">
      <div class="name" :title="item?.name">{{ item ? item.name : '' }}</div>
      <div v-if="mode !== 'small' && item" class="sub">{{ formatSize(item.size) }} · {{ formatDate(item.mtime) }}</div>
      <div v-if="mode === 'small' && item" class="sub-sm">{{ item.ext || '文件' }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Icon from './Icon.vue'
import { formatSize, formatDate } from '../utils/format'
import { fileIcon, fileColor, classifyExt, previewable } from '../utils/fileTypes'
import { apiFiles } from '../api'

const props = defineProps({
  item: { type: Object, default: null },
  mode: { type: String, default: 'medium' },
  selected: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'fav'])

const imgError = ref(false)
const isVideo = computed(() => props.item && classifyExt(props.item.ext) === 'video')
const iconName = computed(() => props.item ? fileIcon(props.item) : 'file')
const iconSize = computed(() => (props.mode === 'small' ? 30 : props.mode === 'large' ? 56 : 42))
const showThumb = computed(() => {
  if (!props.item || imgError.value) return false
  const k = classifyExt(props.item.ext)
  return (k === 'image') && props.mode !== 'small'
})
const thumbUrl = computed(() => {
  if (!props.item || !showThumb.value) return ''
  const cfg = { small: 96, medium: 160, large: 240 }
  return apiFiles.thumbUrl(props.item.id, cfg[props.mode] || 160)
})

function onClick(e) {
  if (!props.item) return
  if (e.altKey || e.ctrlKey || e.metaKey) {
    emit('fav', props.item)
    return
  }
  emit('select', props.item)
}
function onDblClick(e) {
  if (!props.item || e.altKey || e.ctrlKey || e.metaKey) return
  emit('select', props.item)
}
</script>

<style scoped>
.card {
  box-sizing: border-box;
  height: 100%;
  padding: 6px;
  display: flex;
  flex-direction: column;
  border-radius: 8px;
  cursor: default;
  border: 1px solid transparent;
  overflow: hidden;
  user-select: none;
}
.card:hover { background: rgba(255, 255, 255, 0.05); }
.card.selected { background: rgba(76, 139, 245, 0.18); border-color: rgba(76, 139, 245, 0.55); }
.card.missing { opacity: 0.55; }
.thumb {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  overflow: hidden;
  position: relative;
}
.thumb img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
}
.skeleton {
  width: 70%;
  height: 60%;
  border-radius: 6px;
  background: linear-gradient(90deg, rgba(255,255,255,.05), rgba(255,255,255,.1), rgba(255,255,255,.05));
  background-size: 200% 100%;
  animation: sh 1.2s infinite;
}
@keyframes sh { to { background-position: -200% 0; } }
.meta { padding: 4px 2px 0; min-width: 0; }
.name {
  font-size: 12px;
  color: #e3e6eb;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.sub { font-size: 10.5px; color: #8b919a; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub-sm { font-size: 10px; color: #6c727c; margin-top: 1px; }
.play-badge {
  position: absolute; bottom: 6px; right: 6px;
  width: 24px; height: 24px; border-radius: 50%;
  background: rgba(0,0,0,.65); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.dir-badge {
  position: absolute; top: 5px; left: 5px;
  width: 22px; height: 22px; border-radius: 6px;
  background: rgba(232,196,104,.22); color: #e8c468;
  display: flex; align-items: center; justify-content: center;
}
.fav-badge {
  position: absolute; top: 5px; right: 5px;
  width: 22px; height: 22px; border-radius: 50%;
  background: rgba(232,170,40,.25); color: #f5b942;
  display: flex; align-items: center; justify-content: center;
}
.missing-badge {
  position: absolute; top: 6px; left: 6px;
  font-size: 10px; padding: 1px 6px; border-radius: 8px;
  background: rgba(224,92,92,.9); color: #fff;
}
</style>
