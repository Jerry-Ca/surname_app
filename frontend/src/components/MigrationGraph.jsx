import { locationLabel } from '../lib/enums.js'

/**
 * 迁徙关系图（D-04）。
 * 轻量呈现：节点 + 箭头 + 证据编号 + 定位状态，不依赖图表库。
 * 严禁用现代人口分布反推古代迁徙；无法定位的节点只显示文字，不画精确位置。
 */
export default function MigrationGraph({ items = [] }) {
  if (items.length === 0) return null

  return (
    <div className="graph">
      {items.map((item) => (
        <div key={`graph-${item.migration_code}`} className="graph__row">
          <span className="graph__node">{item.from_place?.historical_name ?? '起点不明'}</span>
          <span className="graph__edge">
            <span className="arrow">→</span>
            <code>{item.migration_code}</code>
          </span>
          <span className="graph__node">{item.to_place?.historical_name ?? '终点不明'}</span>
          <span className="graph__status">
            {locationLabel(item.from_place?.location_status)} / {locationLabel(item.to_place?.location_status)}
          </span>
        </div>
      ))}
    </div>
  )
}