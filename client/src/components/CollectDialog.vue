<!-- 收藏整理弹窗：plan 预览 → confirm 执行（复制收藏 + 清理其余） -->
<template>
  <div v-if="open" class="overlay" @click.self="close">
    <div class="dialog" :class="{ wide: plan }">
      <div class="d-head">
        <span><Icon name="package" :size="15" /> 整理收藏</span>
        <button class="x" @click="close"><Icon name="x" :size="15" /></button>
      </div>

      <div class="d-body">
        <!-- 计划预览 -->
        <template v-if="plan">
          <div class="stat-grid">
            <div class="stat"><b>{{ plan.favorite_count }}</b><span>收藏文件</span></div>
            <div class="stat"><b>{{ formatSize(plan.copy_bytes) }}</b><span>待复制</span></div>
            <div class="stat danger"><b>{{ plan.delete_count }}</b><span>待删除</span></div>
            <div class="stat danger"><b>{{ formatSize(plan.delete_bytes) }}</b><span>释放空间</span></div>
          </div>
          <div class="opt-row">
            <label class="chk"><input type="checkbox" v-model="opts.copy" /> 复制收藏到本地目录</label>
            <label class="chk"><input type="checkbox" v-model="opts.cleanup" /> 删除收藏之外的其余内容</label>
            <label class="chk"><input type="checkbox" v-model="opts.remove_empty_roots" /> 删除后移除空目录/空根</label>
          </div>
          <div class="target">
            目标目录：<code>{{ plan.target_dir }}</code>
          </div>
          <div v-if="opts.cleanup && plan.delete_count" class="warn">
            <Icon name="warn" :size="14" />
            即将删除 <b>{{ plan.delete_count }}</b> 个非收藏文件 / {{ plan.delete_dirs }} 个目录（约
            {{ formatSize(plan.delete_bytes) }}）。此操作不可撤销！
          </div>
          <template v-if="plan.samples && plan.samples.length">
            <div class="samples-title">待删除样本（前 {{ plan.samples.length }} 条）：</div>
            <div class="samples">
              <div v-for="(s, i) in plan.samples" :key="i" class="sample" :title="s.path">
                {{ s.path }}
              </div>
            </div>
          </template>
          <div class="d-actions">
            <button class="ghost" @click="refreshPlan"><Icon name="refresh" :size="13" /> 重新计算</button>
            <button class="danger-btn" :disabled="running" @click="run">
              <Icon name="zap" :size="13" :spin="running" />
              {{ running ? '执行中…' : '开始整理' }}
            </button>
          </div>
        </template>

        <!-- 加载中 -->
        <div v-else class="loading"><Icon name="refresh" :size="20" spin /> 正在计算整理计划…</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import Icon from './Icon.vue'
import { apiCollect } from '../api'
import { formatSize } from '../utils/format'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close', 'task', 'done'])

const plan = ref(null)
const running = ref(false)
const opts = ref({ copy: true, cleanup: true, remove_empty_roots: true })

watch(() => props.open, (v) => { if (v) refreshPlan() })

async function refreshPlan() {
  plan.value = null
  try {
    const r = await apiCollect.plan()
    plan.value = r.data
  } catch (e) { alert('计算计划失败: ' + e.message); plan.value = { error: e.message } }
}

async function run() {
  if (!opts.value.copy && !opts.value.cleanup) { alert('至少选择一项操作'); return }
  if (opts.value.cleanup && plan.value.delete_count) {
    const ok = confirm(
      `确认执行整理？\n复制 ${plan.value.favorite_count} 个收藏文件到本地，\n并删除 ${plan.value.delete_count} 个非收藏文件（不可撤销）。`
    )
    if (!ok) return
  }
  running.value = true
  try {
    const r = await apiCollect.run({ copy: opts.value.copy, cleanup: opts.value.cleanup, remove_empty_roots: opts.value.remove_empty_roots })
    if (r.data?.task_id) emit('task', r.data.task_id)
    alert('整理任务已启动，完成后将自动重新索引受影响根目录。')
    emit('done')
    close()
  } catch (e) {
    alert('启动失败: ' + e.message)
  } finally { running.value = false }
}

function close() { emit('close') }
</script>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.dialog {
  width: 560px; max-width: 94vw; max-height: 86vh;
  background: #222428; border: 1px solid #33363d; border-radius: 12px;
  display: flex; flex-direction: column; overflow: hidden;
}
.dialog.wide { width: 680px; }
.d-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; border-bottom: 1px solid #2e3137;
  color: #e3e6eb; font-size: 14px; font-weight: 600;
}
.x { margin-left: auto; background: none; border: none; color: #8b919a; cursor: pointer; padding: 4px; border-radius: 6px; display: flex; }
.x:hover { color: #fff; background: rgba(255,255,255,.08); }
.d-body { padding: 16px; overflow: auto; }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 14px; }
.stat {
  background: #1f2125; border: 1px solid #2e3137; border-radius: 9px;
  padding: 10px; text-align: center;
}
.stat b { display: block; font-size: 17px; color: #6ab0ff; }
.stat.danger b { color: #e05c5c; }
.stat span { font-size: 11px; color: #8b919a; }
.opt-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
.chk { display: inline-flex; align-items: center; gap: 5px; color: #c9cdd4; font-size: 12.5px; cursor: pointer; }
.chk input { accent-color: #3d78e6; }
.target { font-size: 12px; color: #8b919a; margin-bottom: 10px; }
.target code { background: #1a1c1f; padding: 2px 7px; border-radius: 5px; color: #9fd0a9; font-size: 11.5px; }
.warn {
  display: flex; align-items: flex-start; gap: 7px;
  background: rgba(224,92,92,.1); border: 1px solid rgba(224,92,92,.4);
  color: #f0a5a5; border-radius: 8px; padding: 10px 12px; font-size: 12.5px; margin-bottom: 12px;
}
.warn b { color: #fff; }
.samples-title { font-size: 12px; color: #8b919a; margin-bottom: 6px; }
.samples {
  max-height: 150px; overflow: auto; background: #1a1c1f;
  border-radius: 8px; padding: 8px 10px; margin-bottom: 14px;
  font-family: Consolas, monospace; font-size: 11.5px; color: #9aa0a6;
}
.sample { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 1px 0; }
.d-actions { display: flex; justify-content: flex-end; gap: 8px; }
.ghost {
  background: #26282d; border: 1px solid #33363d; color: #c9cdd4;
  border-radius: 7px; padding: 8px 14px; font-size: 12.5px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px;
}
.ghost:hover { color: #fff; }
.danger-btn {
  background: #d64545; color: #fff; border: none; border-radius: 7px;
  padding: 8px 16px; font-size: 12.5px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
}
.danger-btn:hover { background: #e05c5c; }
.danger-btn:disabled { opacity: .6; cursor: default; }
.loading { display: flex; align-items: center; gap: 10px; color: #8b919a; font-size: 13px; padding: 30px 0; justify-content: center; }
</style>
