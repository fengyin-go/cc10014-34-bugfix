import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/monitor'
const columns = [
  "指标编号",
  "关联服务",
  "QPS阈值",
  "延迟阈值",
  "错误率阈值",
  "告警级别",
  "通知渠道",
  "静默分钟"
]
const detailColumns = ["状态", "时间窗分钟", "日志来源", "阈值版本", "生效阈值版本", "截止边界", "最近聚合时间"]
const actions = ["提交校验", "启用监控", "停用监控"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]

type Row = Record<string, string | number | null | string[]>
type Batch = Record<string, string | number | boolean | null>

const emptyForm = {
  指标编号: '',
  关联服务: '',
  QPS阈值: '',
  延迟阈值: '',
  错误率阈值: '',
  告警级别: 'P3',
  通知渠道: '邮件',
  静默分钟: '5',
  时间窗分钟: '60',
  日志来源: '',
  优先级: '0',
}

export default function MonitorView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [form, setForm] = useState<Record<string, string>>({ ...emptyForm })
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Row | null>(null)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [batches, setBatches] = useState<Batch[]>([])
  const [batchMetric, setBatchMetric] = useState('')
  const [reconcile, setReconcile] = useState<Record<string, unknown> | null>(null)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const loadBatches = useCallback(async (metricCode: string) => {
    const query = new URLSearchParams()
    if (metricCode) query.set('metric_code', metricCode)
    query.set('size', '100')
    const response = await request(`${ENDPOINT}/batches?${query.toString()}`)
    if (!response.ok) throw new Error('指标批次读取失败')
    const payload = await response.json()
    setBatches(payload.items ?? [])
  }, [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('监控指标列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
      await loadBatches(batchMetric)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务监控列表读取失败')
    }
  }, [filters, batchMetric, loadBatches])

  useEffect(() => {
    void reload()
  }, [reload])

  async function post(path: string, body: Record<string, unknown>, success: string) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '操作未生效')
      }
      setNotice(payload.message ?? success)
      await reload()
      return true
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务监控操作失败')
      return false
    }
  }

  async function runAction(action: string, row: Row) {
    await post(`${ENDPOINT}/${row.id}/actions`, { action }, '动作已执行')
  }

  async function submitForm() {
    const ok = await post(ENDPOINT, { values: form }, '监控指标已登记')
    if (ok) {
      setShowForm(false)
      setForm({ ...emptyForm })
    }
  }

  function openEdit(row: Row) {
    setEditing(row)
    setEditValues({
      QPS阈值: String(row['QPS阈值'] ?? ''),
      延迟阈值: String(row['延迟阈值'] ?? ''),
      错误率阈值: String(row['错误率阈值'] ?? ''),
      告警级别: String(row['告警级别'] ?? ''),
      通知渠道: String(row['通知渠道'] ?? ''),
      静默分钟: String(row['静默分钟'] ?? ''),
      时间窗分钟: String(row['时间窗分钟'] ?? '60'),
      日志来源: Array.isArray(row['日志来源']) ? row['日志来源'].join(',') : String(row['日志来源'] ?? ''),
      优先级: String(row['优先级'] ?? '0'),
    })
  }

  async function submitEdit() {
    if (!editing) return
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${editing.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ values: editValues }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '阈值未更新')
      }
      setNotice(payload.message ?? '阈值已更新')
      setEditing(null)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '阈值更新失败')
    }
  }

  async function runReconcile() {
    setErrorMessage('')
    setNotice('')
    try {
      const query = batchMetric ? `?metric_code=${encodeURIComponent(batchMetric)}` : ''
      const response = await request(`${ENDPOINT}/reconcile${query}`)
      const payload = await response.json()
      if (!response.ok) throw new Error('复核接口返回异常')
      setReconcile(payload)
      setNotice(payload.ok ? '指标状态、时间窗、日志范围与异常告警一致' : '复核发现不一致项，请查看下方明细')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '复核失败')
    }
  }

  const stats = useMemo(() => ([
    { label: '监控指标总数', value: total },
    { label: '已启用指标', value: rows.filter((row) => row['status'] === '已启用').length },
    { label: '指标批次数', value: batches.length },
    { label: '异常批次数', value: batches.filter((batch) => batch['异常']).length },
  ]), [rows, total, batches])

  return (
    <section className="page" data-module="monitor">
      <header className="page-head">
        <div>
          <h2>服务监控管理</h2>
          <p className="page-desc">维护监控指标的登记、状态流转与聚合口径；停用后时间窗、日志范围与截止边界同步冻结。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setShowForm((prev) => !prev)}>
            登记监控指标
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出服务监控清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      {showForm && (
        <form className="edit-panel" onSubmit={(event) => { event.preventDefault(); void submitForm() }}>
          <h3>登记监控指标</h3>
          <div className="edit-grid">
            {Object.keys(emptyForm).map((field) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={form[field] ?? ''}
                  onChange={(event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
          </div>
          <p className="page-desc">延迟阈值、错误率阈值、通知渠道与静默分钟缺一不可；登记后为草稿，需先提交校验才能启用。</p>
          <div className="row-actions">
            <button className="btn primary" type="submit">保存</button>
            <button className="btn ghost" type="button" onClick={() => setShowForm(false)}>取消</button>
          </div>
        </form>
      )}

      {editing && (
        <form className="edit-panel" onSubmit={(event) => { event.preventDefault(); void submitEdit() }}>
          <h3>修改阈值 · {String(editing['指标编号'])}（当前版本 {String(editing['阈值版本'])}）</h3>
          <div className="edit-grid">
            {Object.keys(editValues).map((field) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={editValues[field] ?? ''}
                  onChange={(event) => setEditValues((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
          </div>
          <p className="page-desc">阈值版本按优先级、版本新旧仲裁；旧版本写入阈值历史，列表与告警详情只显示当前版本。</p>
          <div className="row-actions">
            <button className="btn primary" type="submit">保存新版本</button>
            <button className="btn ghost" type="button" onClick={() => setEditing(null)}>取消</button>
          </div>
        </form>
      )}

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <label className="filter-item">
          <span>状态</span>
          <select
            value={filters.status ?? ''}
            onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
          >
            <option value="">全部</option>
            {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            {detailColumns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{renderCell(row[column])}</td>)}
              <td>{row['status'] ?? '—'}</td>
              <td>{row['时间窗分钟'] ?? '—'}</td>
              <td>{Array.isArray(row['日志来源']) ? row['日志来源'].join('、') : row['日志来源'] ?? '—'}</td>
              <td>{row['阈值版本'] ?? '—'}</td>
              <td>{row['生效阈值版本'] ?? '—'}</td>
              <td>{row['截止边界'] ?? '—'}</td>
              <td>{row['最近聚合时间'] ?? '—'}</td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => openEdit(row)}>修改阈值</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + detailColumns.length + 1}>暂无服务监控数据，可先登记监控指标</td>
            </tr>
          )}
        </tbody>
      </table>

      <section className="sub-panel">
        <header className="page-head">
          <div>
            <h3>指标批次</h3>
            <p className="page-desc">按指标状态与时间窗聚合调用日志；停用指标的批次转入历史范围并保留截止边界。</p>
          </div>
          <div className="page-actions">
            <input
              className="inline-input"
              placeholder="按指标编号过滤批次"
              value={batchMetric}
              onChange={(event) => setBatchMetric(event.target.value)}
            />
            <button className="btn" type="button" onClick={() => void post(`${ENDPOINT}/aggregate`, { 指标编号: batchMetric }, '聚合完成')}>立即聚合</button>
            <button className="btn" type="button" onClick={() => void post(`${ENDPOINT}/retry`, { 指标编号: batchMetric }, '失败记录已重试')}>从失败记录重试</button>
            <button className="btn" type="button" onClick={() => void loadBatches(batchMetric)}>刷新批次</button>
            <button className="btn" type="button" onClick={() => void runReconcile()}>复核一致性</button>
          </div>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>批次编号</th><th>指标编号</th><th>窗口起</th><th>窗口止</th>
              <th>日志数</th><th>错误率</th><th>阈值版本</th><th>范围</th><th>截止边界</th><th>异常</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => (
              <tr key={String(batch['批次编号'])}>
                <td>{String(batch['批次编号'])}</td>
                <td>{String(batch['指标编号'])}</td>
                <td>{String(batch['窗口起'])}</td>
                <td>{String(batch['窗口止'])}</td>
                <td>{String(batch['日志数'])}</td>
                <td>{String(batch['错误率'])}%</td>
                <td>{String(batch['阈值版本'])}</td>
                <td>{String(batch['范围类型'])}</td>
                <td>{batch['截止边界'] ? String(batch['截止边界']) : '—'}</td>
                <td>{batch['异常'] ? `异常：${String(batch['异常原因'])}` : '正常'}</td>
              </tr>
            ))}
            {batches.length === 0 && (
              <tr><td className="empty-state" colSpan={10}>当前过滤条件下没有指标批次</td></tr>
            )}
          </tbody>
        </table>
        {reconcile && (
          <div className="reconcile-box">
            <strong>{reconcile.ok ? '复核通过' : '复核发现不一致'}</strong>
            <pre>{JSON.stringify(reconcile, null, 2)}</pre>
          </div>
        )}
      </section>

      <footer className="page-foot">
        <span>共 {total} 条服务监控记录</span>
        {notice && <span>{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}

function renderCell(value: Row[string]) {
  if (Array.isArray(value)) return value.join('、')
  return value ?? '—'
}
