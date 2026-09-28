<template>
  <section class="page" data-module="baggage">
    <header class="page-head">
      <div>
        <h2>行李装卸管理</h2>
        <p class="page-desc">维护装卸单，支持按装卸车辆分批登记行李件数、多选交接班组；分批合计与登记件数不符时提醒但不阻断保存。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记装卸单</button>
        <button class="btn" type="button" @click="exportRows">导出行李装卸清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="handover-bar">
      <span class="handover-label">班组交接：已选 {{ selectedIds.length }} 条</span>
      <input v-model="handoverTeam" placeholder="目标班组，如：乙班" />
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="submitHandover">
        批量交接
      </button>
      <span v-if="handoverMessage" class="hint-text">{{ handoverMessage }}</span>
    </div>
    <ul v-if="handoverResults.length" class="result-list">
      <li v-for="item in handoverResults" :key="item.id" :class="{ fail: !item.ok }">
        {{ item.label }}：{{ item.message }}
      </li>
    </ul>

    <section v-if="showCreate" class="panel">
      <header class="panel-head">
        <strong>登记装卸单</strong>
        <button class="btn ghost" type="button" @click="showCreate = false">收起</button>
      </header>
      <form class="filter-bar" @submit.prevent="submitCreate">
        <label v-for="field in createFields" :key="field.name" class="filter-item">
          <span>{{ field.label }}</span>
          <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
        </label>
        <button class="btn primary" type="submit">保存装卸单</button>
      </form>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allChecked" @change="toggleAll" />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>分批合计</th>
          <th>差异提醒</th>
          <th>交接</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input type="checkbox" :checked="selectedIds.includes(Number(row.id))" @change="toggleOne(Number(row.id))" />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.分批合计 ?? 0 }}</td>
          <td>
            <span v-if="row.差异提醒" class="warn-text">{{ row.差异提醒 }}</span>
            <span v-else>—</span>
          </td>
          <td>
            <span v-if="row.已交接" class="tag">已交接</span>
            <span v-else>—</span>
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
            <button class="link" type="button" @click="openBatches(Number(row.id))">分批登记</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 4" class="empty-state">暂无行李装卸数据，可先登记装卸单</td>
        </tr>
      </tbody>
    </table>

    <section v-if="activeEntry" class="panel">
      <header class="panel-head">
        <strong>
          分批登记 — {{ activeEntry.装卸单号 }}（登记 {{ activeEntry.行李件数 }} 件，分批合计 {{ activeEntry.分批合计 ?? 0 }} 件）
        </strong>
        <button class="btn ghost" type="button" @click="activeEntry = null">收起</button>
      </header>
      <p v-if="activeEntry.差异提醒" class="warn-text">{{ activeEntry.差异提醒 }}</p>
      <p v-if="activeEntry.已交接" class="hint-text">
        已交接给 {{ activeEntry.作业班组 }}，原班组 {{ activeEntry.原班组 || '（未登记）' }} 只读
      </p>

      <table class="data-table">
        <thead>
          <tr>
            <th>批次</th>
            <th>装卸车辆</th>
            <th>行李件数</th>
            <th>作业班组</th>
            <th>开始时刻</th>
            <th>完成时刻</th>
            <th>登记时刻</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in activeEntry.batches ?? []" :key="batch.批次号">
            <td>第 {{ batch.批次号 }} 批</td>
            <td>{{ batch.装卸车辆 }}</td>
            <td>{{ batch.行李件数 }}</td>
            <td>{{ batch.作业班组 }}</td>
            <td>{{ batch.开始时刻 }}</td>
            <td>{{ batch.完成时刻 || '—' }}</td>
            <td>{{ batch.登记时刻 }}</td>
          </tr>
          <tr v-if="!(activeEntry.batches ?? []).length">
            <td colspan="7" class="empty-state">暂无分批，可在下方登记第一批</td>
          </tr>
        </tbody>
      </table>

      <form class="filter-bar batch-form" @submit.prevent="submitBatch">
        <label v-for="field in batchFields" :key="field.name" class="filter-item">
          <span>{{ field.label }}</span>
          <input v-model="batchForm[field.name]" :placeholder="field.placeholder" />
        </label>
        <button class="btn primary" type="submit">保存分批</button>
      </form>
      <p v-if="batchWarning" class="warn-text">{{ batchWarning }}</p>
      <p v-if="batchError" class="error-text">{{ batchError }}</p>

      <div v-if="(activeEntry.交接历史 ?? []).length" class="history">
        <span class="stat-label">交接历史</span>
        <ul class="result-list">
          <li v-for="(item, index) in activeEntry.交接历史" :key="index">
            {{ item.交接时刻 }}：{{ item.原班组 }} → {{ item.新班组 }}
          </li>
        </ul>
      </div>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条行李装卸记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface Batch {
  批次号: number
  装卸车辆: string
  行李件数: number
  作业班组: string
  开始时刻: string
  完成时刻: string
  登记时刻: string
}

interface HandoverRecord {
  原班组: string
  新班组: string
  交接时刻: string
}

type Row = Record<string, string | number | boolean | null | Batch[] | HandoverRecord[] | undefined> & {
  id: number
  分批合计?: number
  差异提醒?: string
  已交接?: boolean
  原班组?: string
  batches?: Batch[]
  交接历史?: HandoverRecord[]
}

interface HandoverItem {
  id: number
  label: string
  ok: boolean
  message: string
}

const ENDPOINT = '/api/baggage'
const columns = ["装卸单号", "关联航班", "行李件数", "装卸车辆", "作业班组", "开始时刻", "完成时刻", "装卸状态"]
const actions = ["安排作业", "确认完成", "取消作业"]
const createFields = [
  { name: '装卸单号', label: '装卸单号 *', placeholder: '如：BAGG-0004' },
  { name: '关联航班', label: '关联航班 *', placeholder: '如：CA1831' },
  { name: '行李件数', label: '行李件数 *', placeholder: '非负整数' },
  { name: '装卸车辆', label: '装卸车辆', placeholder: '如：行李传送带车01' },
  { name: '作业班组', label: '作业班组', placeholder: '如：甲班' },
]
const batchFields = [
  { name: '装卸车辆', label: '装卸车辆 *', placeholder: '如：行李平板车03' },
  { name: '行李件数', label: '行李件数 *', placeholder: '本批件数，正整数' },
  { name: '作业班组', label: '作业班组 *', placeholder: '如：乙班' },
  { name: '开始时刻', label: '开始时刻 *', placeholder: '如 2026-09-28 09:10' },
  { name: '完成时刻', label: '完成时刻（可后补）', placeholder: '未完成可留空' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const summary = ref<Record<string, number>>({})
const selectedIds = ref<number[]>([])
const handoverTeam = ref('')
const handoverMessage = ref('')
const handoverResults = ref<HandoverItem[]>([])
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const activeEntry = ref<Row | null>(null)
const batchForm = ref<Record<string, string>>({})
const batchWarning = ref('')
const batchError = ref('')

const stats = computed(() => [
  { label: '装卸单数', value: summary.value.装卸单数 ?? 0 },
  { label: '登记件数合计', value: summary.value.登记件数合计 ?? 0 },
  { label: '分批合计', value: summary.value.分批合计 ?? 0 },
  { label: '差异单数', value: summary.value.差异单数 ?? 0 },
  { label: '已交接单数', value: summary.value.已交接单数 ?? 0 },
])

const allChecked = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)

function toggleOne(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => Number(row.id))
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '装卸单登记失败'
      return
    }
    showCreate.value = false
    createForm.value = {}
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸单登记失败'
  }
}

async function submitHandover() {
  errorMessage.value = ''
  handoverMessage.value = ''
  const activeId = activeEntry.value ? Number(activeEntry.value.id) : null
  try {
    const response = await request(`${ENDPOINT}/handover`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value, team: handoverTeam.value }),
    })
    const payload = await response.json()
    handoverMessage.value = payload.message ?? ''
    handoverResults.value = payload.results ?? []
    const failed = new Set(handoverResults.value.filter((item) => !item.ok).map((item) => item.id))
    selectedIds.value = selectedIds.value.filter((id) => failed.has(id))
    await Promise.all([reload(), loadSummary()])
    if (activeId !== null && handoverResults.value.some((item) => item.id === activeId && item.ok)) {
      await openBatches(activeId)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '班组交接失败'
  }
}

async function openBatches(entryId: number) {
  batchError.value = ''
  batchWarning.value = ''
  try {
    const response = await request(`${ENDPOINT}/${entryId}`)
    if (!response.ok) {
      throw new Error('装卸单明细读取失败')
    }
    activeEntry.value = (await response.json()) as Row
    batchForm.value = { 作业班组: String(activeEntry.value.作业班组 ?? '') }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸单明细读取失败'
  }
}

async function submitBatch() {
  if (!activeEntry.value) {
    return
  }
  batchError.value = ''
  batchWarning.value = ''
  try {
    const response = await request(`${ENDPOINT}/${Number(activeEntry.value.id)}/batches`, {
      method: 'POST',
      body: JSON.stringify({ values: batchForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      batchError.value = payload.message ?? '分批登记失败'
      return
    }
    batchWarning.value = payload.warning ?? ''
    activeEntry.value = (payload.entry as Row) ?? activeEntry.value
    batchForm.value = { 作业班组: batchForm.value.作业班组 ?? '' }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '分批登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('行李装卸动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸操作失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      throw new Error('行李装卸汇总读取失败')
    }
    summary.value = (await response.json()) as Record<string, number>
  } catch {
    summary.value = {}
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('装卸单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>

<style scoped>
.handover-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.handover-bar input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
}
.handover-label {
  font-size: 13px;
  color: var(--muted);
}
.panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.warn-text {
  color: #b45309;
}
.hint-text {
  color: var(--muted);
  font-size: 12px;
}
.result-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
}
.result-list li {
  padding: 2px 0;
}
.result-list li.fail {
  color: #b42318;
}
.tag {
  display: inline-block;
  background: #eef4ff;
  color: var(--brand);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
}
.check-col {
  width: 32px;
  text-align: center;
}
.batch-form {
  margin-top: 10px;
}
.history {
  margin-top: 10px;
}
</style>
