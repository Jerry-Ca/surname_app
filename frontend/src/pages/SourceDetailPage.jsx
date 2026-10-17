import { Link, useLocation, useParams } from 'react-router-dom'
import StatePanel from '../components/StatePanel.jsx'

/**
 * 来源详情页（D-02）。
 * 数据由结果页通过路由 state 传入：v1 契约没有单独的 /api/sources 接口，
 * 如需独立接口先改 docs/api-contract.md 并请 C 实现，前端不得直接拼数据库字段。
 */
export default function SourceDetailPage() {
  const { sourceCode } = useParams()
  const { state } = useLocation()
  const source = state?.source

  if (!source) {
    return (
      <div className="source-page">
        <StatePanel
          kind="warn"
          title="缺少来源上下文"
          message={`请从证据卡片的「来源详情」进入，以便同时携带 ${sourceCode} 的书名、版本与访问时间。`}
        />
        <Link className="inline-link" to="/">
          返回搜索
        </Link>
      </div>
    )
  }

  return (
    <div className="source-page">
      <h1>{source.work_title}</h1>
      {source.link_status === 'stale' ? (
        <StatePanel kind="warn" title="来源链接待复查" message="原链接当前不可访问，以下元数据与摘录仍可用于复核。" />
      ) : null}

      <dl className="source-grid">
        <dt>来源编号</dt>
        <dd>{source.source_code}</dd>
        <dt>作者或编者</dt>
        <dd>{source.work_author || '未详'}</dd>
        <dt>朝代</dt>
        <dd>{source.dynasty || '未标注'}</dd>
        <dt>版本</dt>
        <dd>{source.edition || '未标注'}</dd>
        <dt>卷次或篇章</dt>
        <dd>{source.volume_or_section || '未标注'}</dd>
        <dt>页码或定位</dt>
        <dd>{source.page_or_location || '未标注'}</dd>
        <dt>平台</dt>
        <dd>{source.source_provider || '未标注'}</dd>
        <dt>授权状态</dt>
        <dd>{source.license_status || '未标注'}</dd>
        <dt>访问时间</dt>
        <dd>{source.accessed_at || '未记录'}</dd>
        <dt>链接</dt>
        <dd>
          {source.source_url ? (
            <a href={source.source_url} target="_blank" rel="noreferrer">
              {source.source_url}
            </a>
          ) : (
            <span className="muted">未提供可访问链接</span>
          )}
        </dd>
      </dl>

      <Link className="inline-link" to="/">
        返回搜索
      </Link>
    </div>
  )
}