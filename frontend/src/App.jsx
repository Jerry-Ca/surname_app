import { Link, Route, Routes } from 'react-router-dom'
import SearchPage from './pages/SearchPage.jsx'
import SurnameResultPage from './pages/SurnameResultPage.jsx'
import SourceDetailPage from './pages/SourceDetailPage.jsx'

/**
 * 路由骨架（D-01）。
 * 五个必需区域：搜索页 / 结果页 / 来源详情 / 问答区（在结果页内）/ 状态提示（StatePanel）。
 */
export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">
          姓氏郡望与家族迁徙寻根系统
        </Link>
        <span className="tagline">证据优先：每条结论都能展开看到出处</span>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/surname/:name" element={<SurnameResultPage />} />
          <Route path="/source/:sourceCode" element={<SourceDetailPage />} />
          <Route path="*" element={<SearchPage />} />
        </Routes>
      </main>

      <footer className="app-footer">
        <span>不得编造古籍、卷次、年代、原文、地点与迁徙事件 · 无证据时系统回答“当前资料不足以确认”</span>
        <span>接口契约：docs/api-contract.md ｜ 验收标准：docs/acceptance.md</span>
      </footer>
    </div>
  )
}