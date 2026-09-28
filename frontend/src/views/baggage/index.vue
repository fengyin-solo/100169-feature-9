<template>
  <section class="page" data-module="baggage">
    <header class="page-head">
      <div>
        <h2>行李装卸管理</h2>
        <p class="page-desc">按装卸车辆分批登记行李件数与作业时刻，支持多条装卸单一并交接班组；分批合计与登记件数不符时只提醒、不阻断保存。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记装卸单</button>
        <button class="btn" type="button" @click="exportRows">导出行李装卸清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ 'stat-warn': item.warn }">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="() => reload()">
      <label class="filter-item">
        <span>装卸单号</span>
        <input v-model="keyword" placeholder="按装卸单号检索" />
      </label>
      <label class="filter-item">
        <span>装卸状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedIds.length" class="handover-bar">
      <span>已选择 <strong>{{ selectedIds.length }}</strong> 条装卸单</span>
      <input v-model="handoverTeam" placeholder="接收班组名称（必填）" />
      <button class="btn primary" type="button" @click="submitHandover">交接给该班组</button>
      <button class="btn ghost" type="button" @click="clearSelection">取消选择</button>
      <ul v-if="handoverErrors.length" class="handover-errors">
        <li v-for="(err, idx) in handoverErrors" :key="idx">{{ err }}</li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>分批</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="col-check">
            <input type="checkbox" :value="row.id" v-model="selectedIds" />
          </td>
          <td>{{ row['装卸单号'] ?? '—' }}</td>
          <td>{{ row['关联航班'] ?? '—' }}</td>
          <td>{{ row['登记件数'] ?? '—' }}</td>
          <td>{{ row['装卸车辆'] || '—' }}</td>
          <td>{{ row['作业班组'] || '未派班' }}</td>
          <td>{{ row['开始时刻'] || '—' }}</td>
          <td>{{ row['完成时刻'] || '—' }}</td>
          <td>
            <span :class="{ 'mismatch-text': row['件数不符'] }">{{ row['分批合计'] ?? 0 }}</span>
            <em v-if="row['件数不符']" class="warn-tag" :title="mismatchHint(row)">不符</em>
          </td>
          <td>{{ row.status }}</td>
          <td>
            <button class="link" type="button" @click="openBatches(row)">
              分批明细{{ row['分批数'] ? `（${row['分批数']}）` : '' }}
            </button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无行李装卸数据，可先登记装卸单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条行李装卸记录（分批合计与上方汇总卡片口径一致）</span>
      <span v-if="message" :class="messageKind === 'error' ? 'error-text' : 'warn-text'">{{ message }}</span>
    </footer>

    <!-- 登记装卸单 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记装卸单</h3>
        <div v-for="field in createFields" :key="field" class="form-item">
          <label>{{ field }}<em class="required">*</em></label>
          <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">保存</button>
        </div>
      </div>
    </div>

    <!-- 分批明细 + 登记 -->
    <div v-if="batchTarget" class="modal-mask" @click.self="batchTarget = null">
      <div class="modal modal-wide">
        <h3>{{ batchTarget['装卸单号'] }} · 分批明细</h3>
        <p class="modal-sub">
          登记件数 {{ batchTarget['登记件数'] }} 件，分批合计
          <strong :class="{ 'mismatch-text': batchTarget['件数不符'] }">{{ batchTarget['分批合计'] }}</strong> 件
          <em v-if="batchTarget['件数不符']" class="warn-tag">不符，已提醒但不阻断</em>
          <em v-else-if="batchTarget['分批数']" class="ok-tag">相符</em>
        </p>

        <table class="data-table batch-table">
          <thead>
            <tr>
              <th>批次</th><th>装卸车辆</th><th>作业班组</th><th>开始时刻</th><th>完成时刻</th><th>行李件数</th><th>状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(b, idx) in (batchTarget?.['分批明细'] ?? [])" :key="idx">
              <td>第{{ b['序号'] }}批</td>
              <td>{{ b['装卸车辆'] }}</td>
              <td>{{ b['作业班组'] }}</td>
              <td>{{ b['开始时刻'] }}</td>
              <td>{{ b['完成时刻'] }}</td>
              <td>{{ b['行李件数'] }}</td>
              <td>
                <em v-if="b['只读']" class="lock-tag">已交接·只读</em>
                <span v-else>当前班组</span>
              </td>
              <td>
                <button v-if="!b['只读']" class="link danger" type="button" @click="removeBatch(idx)">删除</button>
              </td>
            </tr>
            <tr v-if="!(batchTarget?.['分批明细'] ?? []).length">
              <td colspan="8" class="empty-state">尚无分批记录，可在下方按车辆登记第一批</td>
            </tr>
          </tbody>
        </table>

        <div v-if="batchTarget['已交接']" class="handover-note">
          当前责任班组：{{ batchTarget['作业班组'] }}（原班组登记的历史分批已锁定只读）
        </div>

        <h4 class="form-title">登记新一批</h4>
        <div class="batch-form">
          <label class="form-item">
            <span>装卸车辆<em class="required">*</em></span>
            <input v-model="batchForm['装卸车辆']" placeholder="如 BCT-07" />
          </label>
          <label class="form-item">
            <span>作业班组<em class="required">*</em></span>
            <input v-model="batchForm['作业班组']" :placeholder="batchTarget['作业班组'] ? `当前为 ${batchTarget['作业班组']}` : '班组名称'" />
          </label>
          <label class="form-item">
            <span>开始时刻<em class="required">*</em></span>
            <input v-model="batchForm['开始时刻']" type="datetime-local" />
          </label>
          <label class="form-item">
            <span>完成时刻<em class="required">*</em></span>
            <input v-model="batchForm['完成时刻']" type="datetime-local" />
          </label>
          <label class="form-item">
            <span>行李件数<em class="required">*</em></span>
            <input v-model="batchForm['行李件数']" type="number" min="0" step="1" placeholder="本批件数" />
          </label>
        </div>
        <p v-if="batchWarning" class="warn-text">{{ batchWarning }}</p>
        <p v-if="batchError" class="error-text">{{ batchError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="batchTarget = null">关闭</button>
          <button class="btn primary" type="button" @click="submitBatch">保存本批</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Detail = Row & { '分批明细'?: Row[]; '交接记录'?: Row[] }

interface Summary {
  装卸单总数: number
  登记行李件数合计: number
  分批行李件数合计: number
  分批批次数: number
  件数不符单数: number
  待作业单数: number
}

const ENDPOINT = '/api/baggage'
const columns = ['装卸单号', '关联航班', '登记件数', '装卸车辆', '作业班组', '开始时刻', '完成时刻', '分批合计', '装卸状态']
const actions = ['安排作业', '确认完成', '取消作业']
const statuses = ['待作业', '装卸中', '已完成', '已取消']
const createFields = ['装卸单号', '关联航班', '行李件数']

const rows = ref<Detail[]>([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const message = ref('')
const messageKind = ref<'info' | 'error'>('info')

const summary = ref<Summary>({
  装卸单总数: 0,
  登记行李件数合计: 0,
  分批行李件数合计: 0,
  分批批次数: 0,
  件数不符单数: 0,
  待作业单数: 0,
})
const stats = computed(() => [
  { label: '装卸单总数', value: summary.value.装卸单总数 },
  { label: '登记件数合计', value: summary.value.登记行李件数合计 },
  { label: '分批件数合计', value: summary.value.分批行李件数合计 },
  { label: '分批批次数', value: summary.value.分批批次数 },
  { label: '件数不符提醒', value: summary.value.件数不符单数, warn: summary.value.件数不符单数 > 0 },
])

// ---------------- 多选交接 ----------------
const selectedIds = ref<number[]>([])
const handoverTeam = ref('')
const handoverErrors = ref<string[]>([])
const allChecked = computed(() => rows.value.length > 0 && selectedIds.value.length === rows.value.length)

function toggleAll(event: Event) {
  selectedIds.value = (event.target as HTMLInputElement).checked
    ? rows.value.map((r) => Number(r.id))
    : []
}

function clearSelection() {
  selectedIds.value = []
  handoverTeam.value = ''
  handoverErrors.value = []
}

async function submitHandover() {
  handoverErrors.value = []
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/batches/handover`, {
      method: 'POST',
      body: JSON.stringify({ entry_ids: selectedIds.value, target_team: handoverTeam.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      handoverErrors.value = payload.errors?.length ? payload.errors : [payload.message || '交接失败']
      return
    }
    clearSelection()
    messageKind.value = 'info'
    message.value = payload.message
    await reload()
  } catch (error) {
    handoverErrors.value = [error instanceof Error ? error.message : '交接请求失败']
  }
}

// ---------------- 登记装卸单 ----------------
const createOpen = ref(false)
const createForm = reactive<Record<string, string>>({ 装卸单号: '', 关联航班: '', 行李件数: '' })
const createError = ref('')

function openCreate() {
  createFields.forEach((f) => { createForm[f] = '' })
  createError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: { ...createForm } }) })
    const payload = await response.json()
    if (!payload.ok) {
      createError.value = payload.message
      return
    }
    createOpen.value = false
    messageKind.value = 'info'
    message.value = '装卸单已登记，可在「分批明细」里按车辆登记批次'
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记失败'
  }
}

// ---------------- 分批登记 ----------------
const batchTarget = ref<Detail | null>(null)
const batchForm = reactive<Record<string, string>>({
  装卸车辆: '', 作业班组: '', 开始时刻: '', 完成时刻: '', 行李件数: '',
})
const batchError = ref('')
const batchWarning = ref('')

function emptyBatchForm() {
  Object.keys(batchForm).forEach((k) => { batchForm[k] = '' })
}

async function openBatches(row: Row) {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('分批明细读取失败')
    const detail: Detail = await response.json()
    batchTarget.value = detail
    emptyBatchForm()
    batchForm['作业班组'] = String(detail['作业班组'] ?? '')
    batchError.value = ''
    batchWarning.value = ''
  } catch (error) {
    messageKind.value = 'error'
    message.value = error instanceof Error ? error.message : '分批明细读取失败'
  }
}

function syncTargetFromEntry(entry: Detail) {
  batchTarget.value = entry
}

async function submitBatch() {
  if (!batchTarget.value) return
  batchError.value = ''
  batchWarning.value = ''
  const values: Record<string, string> = { ...batchForm }
  values['开始时刻'] = values['开始时刻'].replace('T', ' ')
  values['完成时刻'] = values['完成时刻'].replace('T', ' ')
  try {
    const response = await request(`${ENDPOINT}/${batchTarget.value.id}/batches`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      batchError.value = payload.message
      return
    }
    syncTargetFromEntry(payload.entry as Detail)
    emptyBatchForm()
    batchWarning.value = payload.warning || ''
    await reload({ silent: true })
    await refreshSummary()
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '分批登记失败'
  }
}

async function removeBatch(index: number) {
  if (!batchTarget.value) return
  batchError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${batchTarget.value.id}/batches/${index}`, {
      method: 'DELETE',
    })
    const payload = await response.json()
    if (!payload.ok) {
      batchError.value = payload.message
      return
    }
    syncTargetFromEntry(payload.entry as Detail)
    batchWarning.value = payload.warning || ''
    await reload({ silent: true })
    await refreshSummary()
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '分批删除失败'
  }
}

// ---------------- 原有动作 / 筛选 / 导出 ----------------
function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '行李装卸动作未生效')
    messageKind.value = 'info'
    message.value = payload.message
    await reload({ silent: true })
  } catch (error) {
    messageKind.value = 'error'
    message.value = error instanceof Error ? error.message : '行李装卸操作失败'
  }
}

function mismatchHint(row: Row) {
  return `分批合计 ${row['分批合计']} 件，与登记的 ${row['登记件数']} 件不符，请核对`
}

async function refreshSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) summary.value = await response.json()
  } catch {
    // 汇总读不出来时保留上一次的值，不阻断列表操作
  }
}

async function reload(options: { silent?: boolean } = {}) {
  if (!options.silent) message.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('装卸单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    selectedIds.value = selectedIds.value.filter((id) => rows.value.some((r) => Number(r.id) === id))
    await refreshSummary()
  } catch (error) {
    messageKind.value = 'error'
    message.value = error instanceof Error ? error.message : '行李装卸列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.col-check { width: 36px; text-align: center; }
.warn-tag { font-style: normal; background: #fef3c7; color: #b45309; border: 1px solid #f59e0b; border-radius: 4px; padding: 0 5px; font-size: 12px; margin-left: 4px; }
.ok-tag { font-style: normal; background: #dcfce7; color: #166534; border-radius: 4px; padding: 0 5px; font-size: 12px; margin-left: 4px; }
.lock-tag { font-style: normal; background: #e2e8f0; color: #475569; border-radius: 4px; padding: 0 5px; font-size: 12px; }
.mismatch-text { color: #b45309; font-weight: 600; }
.warn-text { color: #b45309; }
.stat-warn .stat-value { color: #b45309; }
.link.danger { color: #b42318; }

.handover-bar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px;
  padding: 10px 12px; margin-bottom: 12px; font-size: 13px;
}
.handover-bar input { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; min-width: 200px; }
.handover-errors { flex-basis: 100%; margin: 0; padding-left: 18px; color: #b42318; }
.handover-errors li { margin: 2px 0; }

.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 420px; max-height: 86vh; overflow: auto; }
.modal-wide { width: 880px; }
.modal h3 { margin: 0 0 10px; font-size: 16px; }
.modal-sub { font-size: 13px; color: var(--muted); margin: 0 0 10px; }
.form-title { margin: 14px 0 8px; font-size: 14px; }
.form-item { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; font-size: 13px; }
.form-item label { color: var(--muted); }
.form-item input, .form-item select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.required { color: #b42318; font-style: normal; margin-left: 2px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.batch-table th, .batch-table td { font-size: 12px; padding: 6px 8px; }
.batch-form { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 12px; }
.handover-note { font-size: 12px; color: #475569; background: #f1f5f9; border-radius: 6px; padding: 6px 10px; margin-top: 10px; }
</style>
