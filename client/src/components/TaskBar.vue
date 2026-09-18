<!-- 底部任务栏：展示扫描/整理任务的实时进度（SSE + 轮询兜底） -->
<template>
  <div v-if="tasks.length" class="taskbar">
    <div v-for="t in tasks" :key="t.task_id" class="task-item">
      <Icon name="zap" :size="13" :spin="!t.finished" :style="{ color: tColor(t) }" />
      <span class="t-name">{{ t.name }}</span>
      <span class="t-stage">{{ t.stage }}</span>
      <div class="t-bar">
        <div class="t-fill" :style="{ width: (t.percent || 0) + '%', background: tColor(t) }"></div>
      </div>
      <span class="t-pct">{{ Math.round(t.percent || 0) }}%</span>
      <span v-if="t.finished" class="t-state">{{ stateText(t) }}</span>
      <button v-if="!t.finished" class="t-cancel" title="取消任务" @click="cancelTask(t.task_id)">
        <Icon name="x" :size="12" />
      </button>
    </div>
  </div>
</template>

<script setup>
import Icon from './Icon.vue'
import { tasks, cancelTask } from '../tasks'

function tColor(t) {
  if (t.status === 'FAILED') return '#e05c5c'
  if (t.finished) return '#4caf50'
  return '#4c8bf5'
}
function stateText(t) {
  if (t.status === 'FAILED') return '失败'
  if (t.status === 'CANCELLED') return '已取消'
  return '完成'
}
</script>

<style scoped>
.taskbar {
  display: flex; gap: 8px; padding: 5px 12px;
  background: #1a1c1f; border-top: 1px solid #2e3137;
  overflow-x: auto; flex-wrap: wrap;
}
.task-item {
  display: flex; align-items: center; gap: 7px;
  background: #26282d; border-radius: 7px; padding: 4px 8px;
  font-size: 11.5px; color: #c9cdd4; min-width: 300px; flex: 1 1 320px;
}
.t-name { font-weight: 600; white-space: nowrap; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.t-stage { color: #8b919a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
.t-bar { flex: 1; min-width: 80px; height: 5px; background: #33363d; border-radius: 3px; overflow: hidden; }
.t-fill { height: 100%; border-radius: 3px; transition: width .3s; }
.t-pct { width: 34px; text-align: right; color: #8b919a; }
.t-state { font-size: 10.5px; color: #4caf50; }
.t-cancel {
  background: none; border: none; color: #6c727c; cursor: pointer;
  padding: 2px; display: flex; border-radius: 4px;
}
.t-cancel:hover { color: #e05c5c; }
</style>
