/**
 * 枚举与界面中文的映射（唯一来源：docs/data-dictionary.md 第 3、7 节）。
 * 界面不得直接显示代码值；新增枚举先改数据字典，再改这里。
 */

export const VERIFICATION_STATUS = {
  verified: { label: '已核对', tone: 'ok' },
  pending: { label: '未核对，仅供参考', tone: 'warn' },
  disputed: { label: '有争议', tone: 'warn' },
  link_stale: { label: '链接待复查', tone: 'warn' },
  retracted: { label: '已撤回', tone: 'muted' },
}

export const CONFIDENCE = {
  high: '高',
  medium: '中',
  low: '低',
}

export const LOCATION_STATUS = {
  located: '已定位',
  approximate: '大致范围',
  unlocatable: '无法定位',
}

export const EVIDENCE_TYPE = {
  earliest_attestation: '最早书证',
  commandery: '郡望',
  migration: '迁徙',
  other: '其他',
}

export const MATCH_TYPE = {
  exact: '精确匹配',
  alias: '别名匹配',
  variant: '异体或异写',
  compound: '复姓匹配',
  none: '未匹配',
}

export function statusMeta(status) {
  return VERIFICATION_STATUS[status] ?? { label: status || '状态未知', tone: 'muted' }
}

export function confidenceLabel(value) {
  return CONFIDENCE[value] ?? '未标注'
}

export function locationLabel(value) {
  return LOCATION_STATUS[value] ?? '未知'
}

export const ABSTAIN_TEXT = '当前资料不足以确认'