import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import AskPanel from '../components/AskPanel.jsx'
import EvidenceCard from '../components/EvidenceCard.jsx'
import MigrationGraph from '../components/MigrationGraph.jsx'
import MigrationTimeline from '../components/MigrationTimeline.jsx'
import StatePanel, { STATE_TEXT } from '../components/StatePanel.jsx'
import { MATCH_TYPE } from '../lib/enums.js'

/**
 * 结果页（D-02 — D-05）：四个必需区块 + 问答区 + 异常状态。
 * 数据来源：契约第 4—6 节，全部通过 src/api/client.js 获取，不直连数据库或模型。
 */
export default function SurnameResultPage() {
  const { name } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [overview, earliest, commanderies, migrations, corpusChecks] = await Promise.all([
        api.surnameOverview(name),
        api.earliest(name),
        api.commanderies(name),
        api.migrations(name),
        api.corpusChecks(name),
      ])
      setData({ overview, earliest, commanderies, migrations, corpusChecks })
    } catch (requestError) {
      setError(requestError)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [name])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return (
      <div className="result-page">
        <StatePanel kind="loading" title="正在查询…" message="正在读取证据与来源信息，请稍候。" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="result-page">
        <StatePanel
          kind={error.status === 400 ? 'warn' : 'error'}
          title={error.status === 400 ? '输入无法识别' : '查询失败'}
          message={error.message}
          detail={error.requestId ? `request_id: ${error.requestId}` : null}
          action={{ label: '重试', onClick: load }}
        />
        <Link className="inline-link" to="/">
          返回搜索
        </Link>
      </div>
    )
  }

  const { overview, earliest, commanderies, migrations, corpusChecks } = data
  const coverage = overview.coverage
  const notInCorpus = coverage?.status === 'not_in_corpus'

  return (
    <div className="result-page">
      <div className="result-head">
        <h1>
          {overview.surname.canonical_name}
          {overview.surname.category === 'compound' ? <span className="tag">复姓</span> : null}
        </h1>
        <p className="muted">
          匹配方式：{MATCH_TYPE[overview.surname.match_type] ?? overview.surname.match_type}
          {overview.surname.matched_input && overview.surname.matched_input !== overview.surname.canonical_name
            ? `（你输入的是「${overview.surname.matched_input}」，对应规范姓氏「${overview.surname.canonical_name}」）`
            : null}
        </p>
      </div>

      {notInCorpus ? (
        <StatePanel
          kind="empty"
          title={STATE_TEXT.notInCorpus.title}
          message={coverage.note || STATE_TEXT.notInCorpus.message}
        >
          <CorpusAudit items={corpusChecks.items} summary={corpusChecks.summary} />
        </StatePanel>
      ) : null}

      {!notInCorpus ? (
        <>
          <section>
            <h2>最早书证</h2>
            {earliest.items.length === 0 ? (
              <StatePanel
                kind="empty"
                title={earliest.statement_type === 'insufficient_evidence' ? '证据不足' : '未找到书证'}
                message={earliest.statement}
              />
            ) : (
              <>
                <p className="statement">{earliest.statement}</p>
                {earliest.items.map((item) => (
                  <EvidenceCard key={item.evidence_code} evidence={item} highlight />
                ))}
                <p className="muted">
                  排序依据：{earliest.sort_basis.note}（候选 {earliest.sort_basis.candidates_considered} 条
                  {earliest.sort_basis.excluded?.length ? `，排除 ${earliest.sort_basis.excluded.length} 条` : ''}）
                </p>
              </>
            )}
          </section>

          <section>
            <h2>历史郡望</h2>
            {commanderies.dispute_groups?.length ? (
              <StatePanel kind="warn" title={STATE_TEXT.disputed.title} message={STATE_TEXT.disputed.message}>
                <ul>
                  {commanderies.dispute_groups.map((group) => (
                    <li key={group.dispute_group}>
                      <code>{group.dispute_group}</code> {group.summary}
                    </li>
                  ))}
                </ul>
              </StatePanel>
            ) : null}
            {commanderies.items.length === 0 ? (
              <StatePanel kind="empty" title="暂无郡望记录" message="当前语料中未找到该姓氏可核对的郡望记载。" />
            ) : (
              commanderies.items.map((item) => (
                <EvidenceCard
                  key={item.commanderies_code}
                  evidence={{ ...item.evidence, evidence_code: item.commanderies_code }}
                />
              ))
            )}
          </section>

          <section>
            <h2>迁徙线索</h2>
            {migrations.items.length === 0 ? (
              <StatePanel kind="empty" title={STATE_TEXT.noMigration.title} message={migrations.empty_message} />
            ) : (
              <>
                <MigrationTimeline items={migrations.items} />
                <h3>关系图</h3>
                <MigrationGraph items={migrations.items} />
              </>
            )}
          </section>

          <section>
            <h2>语料审计</h2>
            <CorpusAudit items={corpusChecks.items} summary={corpusChecks.summary} />
          </section>
        </>
      ) : null}

      <AskPanel surname={overview.surname.canonical_name} />

      {overview.data_quality?.caveats?.length ? (
        <StatePanel kind="info" title="数据质量说明">
          <ul>
            {overview.data_quality.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </StatePanel>
      ) : null}
    </div>
  )
}

function CorpusAudit({ items = [], summary }) {
  if (!items.length) {
    return <p className="muted">暂无语料审计记录（B-05 未完成时属于正常情况）。</p>
  }
  return (
    <>
      <p className="muted">
        共查询 {summary?.total_queries ?? items.length} 次，命中 {summary?.total_results ?? 0} 条；
        覆盖语料：{(summary?.corpora_checked ?? []).join('、') || '未记录'}
      </p>
      <table className="corpus-table">
        <thead>
          <tr>
            <th>语料</th>
            <th>查询词</th>
            <th>结果数</th>
            <th>查不到的原因</th>
            <th>查询时间</th>
            <th>操作人</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.search_code}>
              <td>{item.corpus_name}</td>
              <td>{item.query_text}</td>
              <td>{item.result_count}</td>
              <td>{item.no_result_reason || '—'}</td>
              <td>{item.checked_at}</td>
              <td>{item.operator}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}