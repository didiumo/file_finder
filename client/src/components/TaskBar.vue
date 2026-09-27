<!-- 底部任务栏：展示扫描/整理/删除任务的实时进度（完成 3.5s 后自动平滑淡出） -->
<template>
  <div v-if="tasks.length" class="taskbar-wrap">
    <transition-group name="task-fade" tag="div" class="taskbar">
      <div v-for="t in tasks" :key="t.task_id" class="task-item">
        <Icon name="zap" :size="13" :spin="!t.finished" :style="{ color: tColor(t) }" />
        <span class="t-name" :title="t.name">{{ t.name }}</span>
        <span class="t-stage" :title="t.stage">{{ t.stage }}</span>
        <div class="t-bar">
          <div
            class="t-fill"
            :class="{ active: !t.finished }"
            :style="{ width: Math.min(100, Math.max(0, t.displayPercent != null ? t.displayPercent : t.percent)) + '%', background: tColor(t) }"
          ></div>
        </div>
        <span class="t-pct">{{ Math.round(t.displayPercent != null ? t.displayPercent : t.percent) }}%</span>
        <span v-if="t.finished" class="t-state">{{ stateText(t) }}</span>
        <button v-if="!t.finished" class="t-cancel" title="取消任务" @click="cancelTask(t.task_id)">
          <Icon name="x" :size="12" />
        </button>
        <button v-else class="t-cancel" title="关闭" @click="dismissTask(t.task_id)">
          <Icon name="x" :size="12" />
        </button>
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import Icon from './Icon.vue'
import { tasks, cancelTask, removeTask } from '../tasks'

function dismissTask(taskId) {
  removeTask(taskId)
}

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
.taskbar-wrap {
  background: #1a1c1f;
  border-top: 1px solid #2e3137;
  overflow: hidden;
  transition: all 0.3s ease;
}
.taskbar {
  display: flex; gap: 8px; padding: 5px 12px;
  overflow-x: auto; flex-wrap: wrap;
}
.task-item {
  display: flex; align-items: center; gap: 7px;
  background: #26282d; border-radius: 7px; padding: 4px 8px;
  font-size: 11.5px; color: #c9cdd4; min-width: 320px; flex: 1 1 320px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
}

/* 平滑进出过渡 */
.task-fade-enter-active,
.task-fade-leave-active {
  transition: all 0.35s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.task-fade-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}
.task-fade-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
.task-fade-leave-active {
  position: absolute;
}

.t-name { font-weight: 600; white-space: nowrap; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.t-stage { color: #8b919a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
.t-bar { flex: 1; min-width: 80px; height: 6px; background: #33363d; border-radius: 3px; overflow: hidden; }
.t-fill {
  height: 100%; border-radius: 3px;
  transition: width 0.12s linear;
}
.t-fill.active {
  background-image: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.22) 50%, rgba(255,255,255,0) 100%);
  background-size: 200% 100%;
  animation: barShine 1.4s infinite linear;
}
@keyframes barShine {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.t-pct { width: 34px; text-align: right; color: #8b919a; font-variant-numeric: tabular-nums; }
.t-state { font-size: 10.5px; color: #4caf50; }
.t-cancel {
  background: none; border: none; color: #6c727c; cursor: pointer;
  padding: 2px; display: flex; border-radius: 4px;
}
.t-cancel:hover { color: #e05c5c; }
</style>
