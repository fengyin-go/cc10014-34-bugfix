import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import Overview from './views/Overview'
import ServiceView from './views/service'
import FlowView from './views/flow'
import RatelimitView from './views/ratelimit'
import AuthView from './views/auth'
import MonitorView from './views/monitor'
import MonitorBatchView from './views/monitor-batch'
import MonitorAlertView from './views/monitor-alert'
import ConsumerView from './views/consumer'
import VersionView from './views/version'
import CacheView from './views/cache'
import TransformView from './views/transform'
import GatewayView from './views/gateway'
import SchemaView from './views/schema'
import DatasourceView from './views/datasource'
import QueryView from './views/query'
import CleanseView from './views/cleanse'
import LogView from './views/log'
import MockView from './views/mock'
import BackupView from './views/backup'
import NotifyView from './views/notify'

const navItems = [{ label: "运营概览", path: "/" }, { label: "服务注册", path: "/service" }, { label: "查询编排", path: "/flow" }, { label: "接口限流", path: "/ratelimit" }, { label: "鉴权管理", path: "/auth" }, { label: "服务监控", path: "/monitor" }, { label: "指标批次", path: "/monitor/batches" }, { label: "异常告警", path: "/monitor/alerts" }, { label: "消费方登记", path: "/consumer" }, { label: "版本管理", path: "/version" }, { label: "结果缓存", path: "/cache" }, { label: "响应转换", path: "/transform" }, { label: "网关路由", path: "/gateway" }, { label: "接口文档", path: "/schema" }, { label: "数据源配置", path: "/datasource" }, { label: "数据查询", path: "/query" }, { label: "数据清洗", path: "/cleanse" }, { label: "调用日志", path: "/log" }, { label: "模拟数据", path: "/mock" }, { label: "数据备份", path: "/backup" }, { label: "事件通知", path: "/notify" }]

export default function App() {
  const [operator] = useState('值班管理员')

  return (
    <div className="app-shell">
      <aside className="app-side">
        <h1 className="app-title">数据服务编排发布平台</h1>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.path} to={item.path} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-head">
          <span className="head-desc">面向数据分析结果的API服务化、查询编排、接口限流、服务监控、版本管理与消费方登记的数据服务编排发布平台。</span>
          <span className="head-user">当前值班：{operator}</span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/service" element={<ServiceView />} />
          <Route path="/flow" element={<FlowView />} />
          <Route path="/ratelimit" element={<RatelimitView />} />
          <Route path="/auth" element={<AuthView />} />
          <Route path="/monitor" element={<MonitorView />} />
          <Route path="/monitor/batches" element={<MonitorBatchView />} />
          <Route path="/monitor/alerts" element={<MonitorAlertView />} />
          <Route path="/consumer" element={<ConsumerView />} />
          <Route path="/version" element={<VersionView />} />
          <Route path="/cache" element={<CacheView />} />
          <Route path="/transform" element={<TransformView />} />
          <Route path="/gateway" element={<GatewayView />} />
          <Route path="/schema" element={<SchemaView />} />
          <Route path="/datasource" element={<DatasourceView />} />
          <Route path="/query" element={<QueryView />} />
          <Route path="/cleanse" element={<CleanseView />} />
          <Route path="/log" element={<LogView />} />
          <Route path="/mock" element={<MockView />} />
          <Route path="/backup" element={<BackupView />} />
          <Route path="/notify" element={<NotifyView />} />
        </Routes>
      </main>
    </div>
  )
}
