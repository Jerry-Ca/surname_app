/**
 * 状态提示组件（D-05）。
 * 覆盖方案要求的六种异常：未收录、无迁徙记录、来源失效、模型不可用、存在争议、地点无法定位。
 * 任何页面都不允许出现空白：没有内容就必须有解释文案。
 */
export default function StatePanel({ kind = 'info', title, message, detail, action, children }) {
  const tone = TONES[kind] ?? TONES.info
  return (
    <section className={`state-panel state-panel--${tone}`} role={kind === 'error' ? 'alert' : 'status'}>
      {title ? <h3 className="state-panel__title">{title}</h3> : null}
      {message ? <p className="state-panel__message">{message}</p> : null}
      {detail ? <pre className="state-panel__detail">{detail}</pre> : null}
      {children}
      {action ? (
        <button type="button" className="btn btn--ghost" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </section>
  )
}

const TONES = {
  info: 'info',
  loading: 'info',
  empty: 'warn',
  warn: 'warn',
  error: 'error',
  ok: 'ok',
}

/** 预置文案：措辞与 docs/requirements.md 第 6 节一致，不要随手改写 */
export const STATE_TEXT = {
  notInCorpus: {
    title: '当前语料中未收录该姓氏',
    message: '下面是本次查询覆盖的语料范围与查询词。查不到也是一种结论，所以我们把它完整列出来。',
  },
  noMigration: {
    title: '没有可核对的迁徙线索',
    message: '当前资料中未找到可核对的迁徙线索。这不等于历史上没有迁徙，只是我们的语料中没有找到可核对的证据。',
  },
  staleLink: {
    title: '来源链接待复查',
    message: '原链接当前不可访问，书名、卷次、原文与访问时间仍然保留，可据此在别处复核。',
  },
  modelUnavailable: {
    title: '智能摘要暂不可用',
    message: '结构化证据查询不受影响：书证、郡望、迁徙与语料审计仍可正常查看。',
  },
  disputed: {
    title: '存在争议',
    message: '以下说法并列展示，各自保留来源与核对状态，系统不做取舍。',
  },
  unlocatable: {
    title: '地点无法定位',
    message: '该地名的今地无法确定，因此不提供坐标。',
  },
}