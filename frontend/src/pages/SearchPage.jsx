import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const SURNAME_PATTERN = /^[\u4e00-\u9fff]{1,8}$/

/** 搜索页（D-01 / D-02）：输入校验规则与后端一致（契约 1.1 节的 400 条件） */
export default function SearchPage() {
  const [value, setValue] = useState('')
  const [hint, setHint] = useState(null)
  const navigate = useNavigate()

  function submit(event) {
    event.preventDefault()
    const candidate = value.trim()
    if (!candidate) {
      setHint('请输入姓氏后再查询')
      return
    }
    if (!SURNAME_PATTERN.test(candidate)) {
      setHint('仅支持 1—8 个汉字，可输入单姓、复姓或异体写法')
      return
    }
    setHint(null)
    navigate(`/surname/${encodeURIComponent(candidate)}`)
  }

  return (
    <div className="search-page">
      <h1>查一个姓氏的文献证据</h1>
      <p className="lead">
        输入姓氏后可以看到：最早书证、历史郡望、迁徙线索和语料审计。
        每条证据都能展开看到书名、卷次、原文摘录与核对状态；没有证据时，系统会明确告诉你“当前资料不足以确认”。
      </p>

      <form onSubmit={submit} className="search-form">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="例如：李、欧阳"
          aria-label="姓氏"
          autoFocus
        />
        <button type="submit" className="btn">
          查询
        </button>
      </form>
      {hint ? <p className="form-hint">{hint}</p> : null}

      <ul className="expectations">
        <li>未收录的姓氏不会显示空白页，而是列出查过的语料与查询词</li>
        <li>多个互相冲突的说法并列展示，系统不替你取舍</li>
        <li>“最早”指当前语料中可以确认的最早，措辞会明确区分</li>
      </ul>
    </div>
  )
}