import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/monitor-alert'

type Alert = Record<string, unknown>
type Threshold = Record<string, unknown>

const columns = [
  '告警编号',
  '指标编号',
  '批次编号',
  '告警级别',
  '通知渠道',
  '异常原因',
  '触发时间',
  '范围类型',
  '状态',
  '通知状态',
]

export default function MonitorAlertView() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [total, setTotal] = useState(0)
  const [scope, setScope] = useState('全部')
  const [metricCode, setMetricCode] = useState('')
  const [selected, setSelected] = useState<Alert | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams({ scope, size: '100' })
    if (metricCode) query.set('metric_code', metricCode)
    try {
      const response = await request(`${ENDPOINT}?${query.toString()}`)
      if (!response.ok) throw new Error('异常告警列表读取失败')
      const payload = await response.json()
      setAlerts(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '异常告警列表读取失败')
    }
  }, [scope, metricCode])

  useEffect(() => {
    void reload()
  }, [reload])

  async function openDetail(alert: Alert) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${String(alert.id)}`)
      if (!response.ok) throw new Error('告警详情读取失败')
      setSelected(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '告警详情读取失败')
    }
  }

  const current = selected?.['当前阈值'] as Threshold | undefined
  const snapshot = selected?.['阈值快照'] as Threshold | undefined

  return (
    <section className="page" data-module="monitor-alert">
      <header className="page-head">
        <div>
          <h2>异常告警</h2>
          <p className="page-desc">告警只读取监控指标契约里的启用口径；指标停用后告警转历史范围，阈值以当前版本为准。</p>
        </div>
        <div className="page-actions">
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="全部">全部范围</option>
            <option value="当前">当前范围</option>
            <option value="历史">历史范围</option>
          </select>
          <input
            className="inline-input"
            placeholder="按指标编号过滤"
            value={metricCode}
            onChange={(event) => setMetricCode(event.target.value)}
          />
          <button className="btn" type="button" onClick={() => void reload()}>刷新</button>
        </div>
      </header>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>阈值版本</th>
            <th>截止边界</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => (
            <tr key={String(alert.id)}>
              {columns.map((column) => <td key={column}>{String(alert[column] ?? '—')}</td>)}
              <td>{String((alert['当前阈值'] as Threshold | undefined)?.['生效阈值版本']
                ?? (alert['当前阈值'] as Threshold | undefined)?.['阈值版本']
                ?? alert['阈值版本'] ?? '—')}</td>
              <td>{String(alert['截止边界'] ?? '—')}</td>
              <td><button className="link" type="button" onClick={() => void openDetail(alert)}>查看</button></td>
            </tr>
          ))}
          {alerts.length === 0 && (
            <tr><td className="empty-state" colSpan={columns.length + 3}>当前过滤条件下没有异常告警</td></tr>
          )}
        </tbody>
      </table>

      {selected && (
        <section className="sub-panel">
          <header className="page-head">
            <div>
              <h3>告警详情 · {String(selected['告警编号'])}</h3>
              <p className="page-desc">
                指标状态：{String(selected['指标状态'] ?? '—')} · 契约：{String(selected['契约编号'] ?? '—')} ·
                批次：{String(selected['批次编号'] ?? '—')}
              </p>
            </div>
            <button className="btn ghost" type="button" onClick={() => setSelected(null)}>关闭</button>
          </header>
          <div className="detail-grid">
            <div>
              <h4>当前阈值（来自契约）</h4>
              <pre>{JSON.stringify(current ?? {}, null, 2)}</pre>
            </div>
            <div>
              <h4>批次阈值快照（异常判断依据）</h4>
              <pre>{JSON.stringify(snapshot ?? {}, null, 2)}</pre>
            </div>
          </div>
          <p className="page-desc">异常原因：{String(selected['异常原因'] ?? '—')}</p>
          <p className="page-desc">
            截止边界：{String(selected['截止边界'] ?? '—')} · 静默：{String(selected['静默分钟'] ?? '—')} 分钟 ·
            通知状态：{String(selected['通知状态'] ?? '—')}
          </p>
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 条异常告警</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
