import { locationLabel } from '../lib/enums.js'

/**
 * 迁徙时间线（D-04）。
 * 规则：时间不精确时显示原文表述（time_label），不伪造精确年份；
 * 地点无法定位时显示“无法定位”，不显示坐标。
 */
export default function MigrationTimeline({ items = [] }) {
  return (
    <ol className="timeline">
      {items.map((item) => (
        <li key={item.migration_code} className="timeline__item">
          <div className="timeline__time">{item.time_label || '时间不明'}</div>
          <div className="timeline__body">
            <p className="timeline__route">
              <span>{item.from_place?.historical_name ?? '起点不明'}</span>
              <span className="arrow">→</span>
              <span>{item.to_place?.historical_name ?? '终点不明'}</span>
            </p>
            <p>{item.event_summary}</p>
            <p className="timeline__meta">
              <span>{item.migration_code}</span>
              <span>可信度：{item.confidence ?? '未标注'}</span>
              <span>关系：{item.relation_status === 'disputed' ? '有争议' : item.relation_status === 'agreed' ? '无争议' : '关系不明确'}</span>
              <span>起点：{locationLabel(item.from_place?.location_status)}</span>
              <span>终点：{locationLabel(item.to_place?.location_status)}</span>
            </p>
            <p className="timeline__evidences">
              证据：
              {(item.evidences ?? []).map((evidence) => (
                <code key={evidence.evidence_code}>{evidence.evidence_code}</code>
              ))}
              {(item.evidences ?? []).length === 0 ? <span className="muted">未挂证据（不得作为结论展示）</span> : null}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}