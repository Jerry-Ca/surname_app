import { useState } from 'react'
import { Link } from 'react-router-dom'
import { confidenceLabel, statusMeta } from '../lib/enums.js'

/**
 * 证据卡片（D-03）：显示事实、原文摘录、书名、卷次、链接、核对状态、可信度。
 * 每条证据都必须能展开看到出处；链接失效时保留元数据并标注“链接待复查”。
 */
export default function EvidenceCard({ evidence, highlight = false }) {
  const [open, setOpen] = useState(false)
  const status = statusMeta(evidence.verification_status)
  const sources = evidence.sources ?? []

  return (
    <article className={`evidence-card${highlight ? ' evidence-card--highlight' : ''}`}>
      <header className="evidence-card__head">
        <span className={`tag tag--${status.tone}`}>{status.label}</span>
        <span className="evidence-card__code">{evidence.evidence_code}</span>
        <span className="evidence-card__meta">
          可信度：{confidenceLabel(evidence.confidence)}
        </span>
      </header>

      <p className="evidence-card__claim">{evidence.claim_text}</p>

      <dl className="evidence-card__grid">
        {evidence.time_label ? (
          <>
            <dt>时间</dt>
            <dd>{evidence.time_label}</dd>
          </>
        ) : null}
        {evidence.volume_or_section ? (
          <>
            <dt>卷次或篇章</dt>
            <dd>{evidence.volume_or_section}</dd>
          </>
        ) : null}
        <dt>来源</dt>
        <dd>
          {sources.length === 0 ? '未登记来源' : sources.map((source) => source.work_title).join('、')}
        </dd>
      </dl>

      {open ? (
        <div className="evidence-card__detail">
          <h4>原文短摘录</h4>
          <blockquote>{evidence.original_excerpt}</blockquote>
          <h4>出处</h4>
          <ul className="source-list">
            {sources.map((source) => (
              <li key={`${evidence.evidence_code}-${source.source_code}`}>
                <strong>{source.work_title}</strong>
                {source.work_author ? `（${source.work_author}）` : null}
                {source.volume_or_section ? ` · ${source.volume_or_section}` : null}
                {source.page_or_location ? ` · ${source.page_or_location}` : null}
                <br />
                {source.source_url ? (
                  <a href={source.source_url} target="_blank" rel="noreferrer">
                    打开来源
                  </a>
                ) : (
                  <span className="muted">未提供可访问链接</span>
                )}
                {source.link_status === 'stale' ? <span className="tag tag--warn">链接待复查</span> : null}
                {source.accessed_at ? <span className="muted"> · 访问时间 {source.accessed_at}</span> : null}
                <Link className="inline-link" to={`/source/${source.source_code}`} state={{ source }}>
                  来源详情
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <button type="button" className="btn btn--link" onClick={() => setOpen((value) => !value)}>
        {open ? '收起出处' : '展开出处'}
      </button>
    </article>
  )
}