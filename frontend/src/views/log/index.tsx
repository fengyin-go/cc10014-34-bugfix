import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/log'
const columns = [
  "记录编号",
  "调用服务",
  "请求时间",
  "响应耗时",
  "返回码",
  "调用方IP",
  "请求大小KB",
  "响应大小KB"
]
const actions = [
  "归档记录",
  "清理日志",
  "导出日志"
]
const statuses = [
  "草稿",
  "记录中",
  "已归档",
  "已清理"
]
const emptyForm = {
  记录编号: '',
  调用服务: '',
  请求时间: '',
  响应耗时: '',
  返回码: '200',
  调用方IP: '',
  请求大小KB: '',
  响应大小KB: '',
}

type Row = Record<string, string | number | null>

export default function LogView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [form, setForm] = useState<Record<string, string>>({ ...emptyForm })
  const [showForm, setShowForm] = useState(false)
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('日志记录列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '调用日志列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '调用日志动作未生效')
      }
      setNotice(payload.message ?? action)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '调用日志操作失败')
    }
  }

  async function submitForm() {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: form }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '日志记录未登记')
      }
      const entry = payload.entry ?? {}
      const scope = entry['聚合状态'] === '已聚合'
        ? `已并入指标批次 ${String(entry['指标批次'])}`
        : String(entry['失败原因'] ?? '')
      setNotice(`日志记录已登记：${scope}`)
      setShowForm(false)
      setForm({ ...emptyForm })
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '日志记录登记失败')
    }
  }

  const stats = useMemo(() => ([
    { label: '日志记录总数', value: total },
    { label: '已聚合日志', value: rows.filter((row) => row['聚合状态'] === '已聚合').length },
    { label: '超范围日志', value: rows.filter((row) => row['聚合状态'] === '超范围').length },
    { label: '聚合失败日志', value: rows.filter((row) => row['聚合状态'] === '失败').length },
  ]), [rows, total])

  return (
    <section className="page" data-module="log">
      <header className="page-head">
        <div>
          <h2>调用日志管理</h2>
          <p className="page-desc">登记调用日志后立即按启用指标的时间窗与日志范围聚合；停用指标之后的迟到日志记为超范围，可重试。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setShowForm((prev) => !prev)}>
            登记日志记录
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出调用日志清单
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
          <h3>登记调用日志</h3>
          <div className="edit-grid">
            {Object.keys(emptyForm).map((field) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={form[field] ?? ''}
                  placeholder={field === '请求时间' ? 'YYYY-MM-DD HH:MM:SS' : undefined}
                  onChange={(event) => setForm((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
          </div>
          <p className="page-desc">写入后会立即尝试聚合：启用指标且落在日志范围内才计入批次，否则保留原因便于复核。</p>
          <div className="row-actions">
            <button className="btn primary" type="submit">保存</button>
            <button className="btn ghost" type="button" onClick={() => setShowForm(false)}>取消</button>
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
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>聚合状态</th>
            <th>指标批次</th>
            <th>失败原因</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td>{String(row['聚合状态'] ?? '待聚合')}</td>
              <td>{String(row['指标批次'] ?? '—')}</td>
              <td>{String(row['失败原因'] ?? '—')}</td>
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 4}>暂无调用日志数据，可先登记日志记录</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条调用日志记录</span>
        {notice && <span>{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
