import { useState } from 'react'
import { api } from '../api/client.js'
import { ABSTAIN_TEXT } from '../lib/enums.js'
import StatePanel, { STATE_TEXT } from './StatePanel.jsx'

/**
 * 证据问答区（契约第 8 节）。
 * 三种情况都必须能显示：基于证据回答 / 证据不足（当前资料不足以确认）/ 模型不可用（降级）。
 */
export default function AskPanel({ surname }) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    try {
      setResult(await api.ask({ surname, question: question.trim(), top_k: 8 }))
    } catch (requestError) {
      setError(requestError)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="ask-panel">
      <h2>证据问答</h2>
      <form onSubmit={submit} className="ask-panel__form">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：这个姓氏的郡望在哪些文献中有记载？"
          maxLength={500}
          aria-label="问题"
        />
        <button type="submit" className="btn" disabled={loading}>
          {loading ? '检索中…' : '提问'}
        </button>
      </form>

      {error ? (
        <StatePanel kind="error" title="问答请求失败" message={error.message} detail={error.requestId ? `request_id: ${error.requestId}` : null} />
      ) : null}

      {result ? (
        <>
          {result.answer_mode === 'degraded_no_model' ? (
            <StatePanel kind="warn" title={STATE_TEXT.modelUnavailable.title} message={result.notice ?? STATE_TEXT.modelUnavailable.message} />
          ) : null}
          {result.answer_mode === 'insufficient_evidence' ? (
            <StatePanel kind="empty" title="证据不足" message={result.answer || ABSTAIN_TEXT} />
          ) : null}
          {result.answer_mode === 'evidence_grounded' ? <p className="ask-panel__answer">{result.answer}</p> : null}

          {result.citations?.length ? (
            <div className="ask-panel__citations">
              <h3>引用证据</h3>
              <ul>
                {result.citations.map((citation) => (
                  <li key={citation.evidence_code}>
                    <code>{citation.evidence_code}</code>
                    <strong>{citation.work_title}</strong>
                    {citation.volume_or_section ? <span> · {citation.volume_or_section}</span> : null}
                    <p className="muted">{citation.original_excerpt}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  )
}