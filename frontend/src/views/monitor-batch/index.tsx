import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/monitor-batch'

type Batch = Record<string, string | number | boolean | null>
type Evidence = Record<string, string | number | null>

const columns = [
  '批次编号',
  '指标编号',
  '窗口起',
  '窗口止',
  '日志数',
  '错误率',
  '阈值版本',
  '范围类型',
  '截止边界',
]

export default function MonitorBatchView() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [total, setTotal] = useState(0)
  const [metricCode, setMetricCode] = useState('')
  const [scope, setScope] = useState('')
  const [onlyAbnormal, setOnlyAbnormal] = useState(false)
  const [selected, setSelected] = useState<Batch | null>(null)
  const [notice, setNotice] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams({ size: '100' })
    if (metricCode) query.set('metric_code', metricCode)
    if (scope) query.set('scope', scope)
    if (onlyAbnormal) query.set('abnormal', '1')
    try {
      const response = await request(`${ENDPOINT}?${query.toString()}`)
      if (!response.ok) throw new Error('指标批次读取失败')
      const payload = await response.json()
      setBatches(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标批次读取失败')
    }
  }, [metricCode, scope, onlyAbnormal])

  useEffect(() => {
    void reload()
  }, [reload])

  function download(format: 'json' | 'csv' | 'zip') {
    const query = new URLSearchParams({ format })
    if (scope) query.set('scope', scope)
    if (onlyAbnormal) query.set('only_abnormal', 'true')
    window.open(`${ENDPOINT}/export?${query.toString()}`, '_blank')
  }

  async function importFile(file: File) {
    setErrorMessage('')
    setNotice('')
    try {
      let body: Record<string, unknown>
      if (file.name.endsWith('.zip')) {
        const buffer = await file.arrayBuffer()
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)))
        body = { package: base64 }
      } else {
        const text = await file.text()
        body = JSON.parse(text)
      }
      const response = await request(`${ENDPOINT}/import`, {
        method: 'POST',
        body: JSON.stringify(body.items ? body : { items: body }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? payload.detail ?? '导入未生效')
      }
      setNotice(payload.message ?? '导入完成')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '导入失败')
    }
  }

  return (
    <section className="page" data-module="monitor-batch">
      <header className="page-head">
        <div>
          <h2>指标批次</h2>
          <p className="page-desc">异常指标批次可导出文件、下载 CSV/ZIP 打包并重新导入；导入后保留原批次编号、阈值快照与逐条日志证据。</p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => download('json')}>导出 JSON</button>
          <button className="btn" type="button" onClick={() => download('csv')}>下载 CSV</button>
          <button className="btn primary" type="button" onClick={() => download('zip')}>打包下载 ZIP</button>
          <label className="btn">
            导入批次证据
            <input
              type="file"
              accept=".json,.zip"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void importFile(file)
                event.target.value = ''
              }}
            />
          </label>
        </div>
      </header>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        <label className="filter-item">
          <span>指标编号</span>
          <input value={metricCode} onChange={(event) => setMetricCode(event.target.value)} placeholder="按指标编号过滤" />
        </label>
        <label className="filter-item">
          <span>范围</span>
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="">全部</option>
            <option value="当前">当前范围</option>
            <option value="历史">历史范围</option>
          </select>
        </label>
        <label className="filter-item">
          <span>仅异常</span>
          <input type="checkbox" checked={onlyAbnormal} onChange={(event) => setOnlyAbnormal(event.target.checked)} />
        </label>
        <button className="btn" type="submit">查询</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>异常判断</th>
            <th>证据</th>
          </tr>
        </thead>
        <tbody>
          {batches.map((batch) => (
            <tr key={String(batch['批次编号'])}>
              {columns.map((column) => <td key={column}>{String(batch[column] ?? '—')}</td>)}
              <td>{batch['异常'] ? `异常：${String(batch['异常原因'])}` : '正常'}</td>
              <td><button className="link" type="button" onClick={() => setSelected(batch)}>查看证据</button></td>
            </tr>
          ))}
          {batches.length === 0 && (
            <tr><td className="empty-state" colSpan={columns.length + 2}>当前过滤条件下没有指标批次</td></tr>
          )}
        </tbody>
      </table>

      {selected && (
        <section className="sub-panel">
          <header className="page-head">
            <div>
              <h3>批次证据 · {String(selected['批次编号'])}</h3>
              <p className="page-desc">
                阈值快照 {JSON.stringify(selected['阈值快照'] ?? {})} · 截止边界 {String(selected['截止边界'] ?? '—')}
              </p>
            </div>
            <button className="btn ghost" type="button" onClick={() => setSelected(null)}>关闭</button>
          </header>
          <table className="data-table">
            <thead>
              <tr><th>记录编号</th><th>请求时间</th><th>响应耗时</th><th>返回码</th><th>调用服务</th></tr>
            </thead>
            <tbody>
              {((selected['证据'] as unknown as Evidence[] | undefined) ?? []).map((item) => (
                <tr key={String(item['日志ID'] ?? item['记录编号'])}>
                  <td>{String(item['记录编号'] ?? '—')}</td>
                  <td>{String(item['请求时间'] ?? '—')}</td>
                  <td>{String(item['响应耗时'] ?? '—')}</td>
                  <td>{String(item['返回码'] ?? '—')}</td>
                  <td>{String(item['调用服务'] ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 个指标批次</span>
        {notice && <span>{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
