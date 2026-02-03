import { useState, useEffect, useMemo } from 'react'
import { generateReviewFast, exportReview, getPapersByIds, refineReview, type PaperBrief } from '../api'
import './Review.css'

const REVIEW_HISTORY_KEY = 'lit_review_history'
const MAX_HISTORY = 10

type ReviewHistoryItem = {
  id: string
  topic: string
  startYear: number | undefined
  endYear: number | undefined
  draft: string
  paperIds: string[]
  createdAt: string
}

function loadReviewHistory(): ReviewHistoryItem[] {
  try {
    const raw = localStorage.getItem(REVIEW_HISTORY_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr.slice(0, MAX_HISTORY) : []
  } catch {
    return []
  }
}

function saveReviewHistory(items: ReviewHistoryItem[]) {
  try {
    localStorage.setItem(REVIEW_HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)))
  } catch {}
}

function parseChapters(text: string): { title: string; content: string }[] {
  if (!text.trim()) return []
  const parts = text.split(/(?=^[一二三四五六七八九十]+[、．.]\s*)/m).filter(Boolean)
  if (parts.length <= 1 && !/^[一二三四五六七八九十]+[、．.]/m.test(parts[0] || '')) {
    return [{ title: '全文', content: text.trim() }]
  }
  return parts.map((p) => {
    const m = p.match(/^([一二三四五六七八九十]+[、．.]\s*[^\n]*)\n?([\s\S]*)/m)
    if (m) {
      return { title: m[1].trim(), content: (m[2] || '').trim() }
    }
    return { title: '段落', content: p.trim() }
  }).filter((c) => c.content.trim() || c.title === '全文')
}

/** 将 AI 输出的 **加粗** 等 Markdown 符号渲染为 HTML（加粗、保留换行） */
function renderDraftContent(content: string) {
  if (!content) return null
  const parts = content.split(/\*\*/)
  return (
    <span style={{ whiteSpace: 'pre-wrap' as const }}>
      {parts.map((part, i) =>
        i % 2 === 1 ? <strong key={i}>{part}</strong> : part
      )}
    </span>
  )
}

export function ReviewPage() {
  const [topic, setTopic] = useState('数字贸易规则')
  const [startYear, setStartYear] = useState<number | undefined>(2018)
  const [endYear, setEndYear] = useState<number | undefined>(2024)
  const [draft, setDraft] = useState('')
  const [paperIds, setPaperIds] = useState<string[]>([])
  const [refPapers, setRefPapers] = useState<PaperBrief[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({})
  const [history, setHistory] = useState<ReviewHistoryItem[]>([])
  const [refineInput, setRefineInput] = useState('')
  const [refineLoading, setRefineLoading] = useState(false)

  useEffect(() => {
    setHistory(loadReviewHistory())
  }, [])

  useEffect(() => {
    if (paperIds.length === 0) {
      setRefPapers([])
      return
    }
    getPapersByIds(paperIds)
      .then(setRefPapers)
      .catch(() => setRefPapers([]))
  }, [paperIds.join(',')])

  const chapters = useMemo(() => parseChapters(draft), [draft])

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setDraft('')
    setPaperIds([])
    try {
      const res = await generateReviewFast({ topic, startYear, endYear })
      setDraft(res.draft)
      setPaperIds(res.paperIds ?? [])
      setCollapsed({})
      const item: ReviewHistoryItem = {
        id: String(Date.now()),
        topic,
        startYear,
        endYear,
        draft: res.draft,
        paperIds: res.paperIds ?? [],
        createdAt: new Date().toISOString(),
      }
      setHistory((prev) => {
        const next = [item, ...prev.filter((h) => h.id !== item.id)]
        saveReviewHistory(next)
        return next
      })
    } catch (err: any) {
      const msg = err?.name === 'AbortError' ? '生成超时（已等待约 3 分钟），请检查网络或稍后重试。' : (err?.message || '生成失败')
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  function handleExport(format: 'txt' | 'latex') {
    if (!draft) return
    exportReview(draft, format).then(({ content, filename }) => {
      const blob = new Blob([content], { type: format === 'latex' ? 'application/x-tex' : 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    }).catch((e) => setError(e?.message || '导出失败'))
  }

  async function handleRefine() {
    if (!draft.trim() || !refineInput.trim() || refineLoading) return
    setRefineLoading(true)
    setError(null)
    try {
      const { draft: refined } = await refineReview({
        draft,
        question: refineInput.trim(),
        topic,
        paperIds: paperIds.length ? paperIds : undefined,
      })
      setDraft(refined)
      setRefineInput('')
      setCollapsed({})
    } catch (err: any) {
      const msg = err?.name === 'AbortError' ? '请求超时，请稍后重试。' : (err?.message || '完善失败')
      setError(msg)
    } finally {
      setRefineLoading(false)
    }
  }

  function toggleChapter(i: number) {
    setCollapsed((prev) => ({ ...prev, [i]: !prev[i] }))
  }

  function expandAll() {
    setCollapsed({})
  }

  function collapseAll() {
    const allCollapsed: Record<number, boolean> = {}
    chapters.forEach((_, i) => { allCollapsed[i] = true })
    setCollapsed(allCollapsed)
  }

  function loadFromHistory(item: ReviewHistoryItem) {
    setTopic(item.topic)
    setStartYear(item.startYear)
    setEndYear(item.endYear)
    setDraft(item.draft)
    setPaperIds(item.paperIds)
    setError(null)
    setCollapsed({})
  }

  function deleteHistoryItem(e: React.MouseEvent, item: ReviewHistoryItem) {
    e.stopPropagation()
    setHistory((prev) => {
      const next = prev.filter((h) => h.id !== item.id)
      saveReviewHistory(next)
      return next
    })
  }

  return (
    <div className="review-page">
      {/* 历史记录侧栏 */}
      <aside className="review-history-sidebar">
        <h4 className="history-title">历史记录</h4>
        <p className="history-hint">最近 {MAX_HISTORY} 条，点击可恢复</p>
        <ul className="history-list">
          {history.length === 0 && <li className="history-empty">暂无记录</li>}
          {history.map((item) => (
            <li key={item.id}>
              <div className="history-item">
                <button type="button" className="history-item-btn" onClick={() => loadFromHistory(item)}>
                  <span className="history-item-topic">{item.topic || '未命名'}</span>
                  <span className="history-item-date">{new Date(item.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                </button>
                <button
                  type="button"
                  className="history-item-delete"
                  onClick={(e) => deleteHistoryItem(e, item)}
                  title="删除"
                  aria-label="删除"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    <line x1="10" y1="11" x2="10" y2="17" />
                    <line x1="14" y1="11" x2="14" y2="17" />
                  </svg>
                  <span className="history-item-delete-text">删除</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      </aside>
      <div className="review-main">
      {/* 页面头部 */}
      <header className="page-header">
        <div className="page-title-section">
          <h1 className="page-title">综述编辑器</h1>
          <p className="page-subtitle">AI 驱动的文献综述自动生成</p>
        </div>
      </header>

      {/* 生成表单 */}
      <div className="review-form card">
        <div className="form-row">
          <div className="form-group form-group-topic">
            <label className="form-label">研究主题</label>
            <input 
              value={topic} 
              onChange={(e) => setTopic(e.target.value)} 
              placeholder="输入综述研究主题"
              className="form-input"
            />
          </div>
          <div className="form-group">
            <label className="form-label">起始年份</label>
            <input 
              type="number" 
              value={startYear ?? ''} 
              onChange={(e) => setStartYear(e.target.value ? Number(e.target.value) : undefined)} 
              placeholder="如 2018"
              className="form-input year-input"
            />
          </div>
          <div className="form-group">
            <label className="form-label">结束年份</label>
            <input 
              type="number" 
              value={endYear ?? ''} 
              onChange={(e) => setEndYear(e.target.value ? Number(e.target.value) : undefined)} 
              placeholder="如 2024"
              className="form-input year-input"
            />
          </div>
          <div className="form-group form-group-btn">
            <button className="btn primary generate-btn" onClick={handleGenerate} disabled={loading}>
              {loading ? (
                <>
                  <span className="loading-spinner-small"></span>
                  生成中（约 1-2 分钟）
                </>
              ) : (
                <>✨ 生成综述草稿</>
              )}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {/* 生成中状态 */}
      {loading && (
        <div className="generating-state card">
          <div className="generating-animation">
            <div className="generating-dot"></div>
            <div className="generating-dot"></div>
            <div className="generating-dot"></div>
          </div>
          <h3>正在生成综述草稿</h3>
          <p>AI 正在分析文献并撰写综述，请耐心等待...</p>
          <div className="progress-bar">
            <div className="progress-fill"></div>
          </div>
        </div>
      )}

      {/* 综述内容 */}
      {draft && !loading && (
        <div className="review-content">
          {/* 工具栏 */}
          <div className="review-toolbar">
            <div className="toolbar-left">
              <span className="toolbar-icon">📄</span>
              <h3>综述草稿</h3>
              <span className="chapter-count">{chapters.length} 个章节</span>
            </div>
            <div className="toolbar-right">
              <button className="btn btn-sm" onClick={expandAll}>
                <span>📖</span> 展开全部
              </button>
              <button className="btn btn-sm" onClick={collapseAll}>
                <span>📕</span> 折叠全部
              </button>
              <div className="toolbar-divider"></div>
              <button className="btn btn-sm" onClick={() => handleExport('txt')}>
                <span>📥</span> 导出 TXT
              </button>
              <button className="btn btn-sm secondary" onClick={() => handleExport('latex')} title="由 AI 生成标准 LaTeX 文件，含分段与标题格式">
                <span>📐</span> 导出 LaTeX
              </button>
            </div>
          </div>

          {/* 章节列表 */}
          <div className="chapters-container card">
            {chapters.map((ch, i) => (
              <div key={i} className={`chapter-block ${collapsed[i] ? 'collapsed' : ''}`}>
                <button
                  type="button"
                  className="chapter-header"
                  onClick={() => toggleChapter(i)}
                  aria-expanded={!collapsed[i]}
                >
                  <span className="chapter-index">{String(i + 1).padStart(2, '0')}</span>
                  <span className="chapter-title">{ch.title}</span>
                  <span className="chapter-toggle">
                    {collapsed[i] ? '▶' : '▼'}
                  </span>
                </button>
                {!collapsed[i] && (
                  <div className="chapter-content">
                    <div className="chapter-body">{renderDraftContent(ch.content)}</div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* 引用文献 */}
          {refPapers.length > 0 && (
            <div className="references-section card">
              <div className="references-header">
                <span className="ref-icon">📚</span>
                <h4>引用文献</h4>
                <span className="ref-count">{refPapers.length} 篇</span>
              </div>
              <ol className="references-list">
                {refPapers.map((p, i) => (
                  <li key={p.id} className="reference-item">
                    <span className="ref-number">[{i + 1}]</span>
                    <div className="ref-content">
                      <span className="ref-title">{p.title}</span>
                      {p.authors?.length ? <span className="ref-authors">{p.authors.join(', ')}</span> : null}
                      <span className="ref-meta">
                        {p.year != null && <span className="ref-year">{p.year}</span>}
                        {p.journal && <span className="ref-journal">{p.journal}</span>}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* AI 对话完善综述 */}
          <div className="review-refine-section card">
            <div className="review-refine-header">
              <span className="refine-icon">💬</span>
              <h4>AI 对话完善综述</h4>
              <p className="refine-hint">输入修改意见或问题，AI 将直接输出修改后的完整草稿</p>
            </div>
            <div className="review-refine-input-row">
              <input
                type="text"
                className="review-refine-input"
                value={refineInput}
                onChange={(e) => setRefineInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleRefine()}
                placeholder="例如：请补充第三部分的案例；或：把第二段写得更简洁"
                disabled={refineLoading}
              />
              <button
                type="button"
                className="btn primary review-refine-btn"
                onClick={handleRefine}
                disabled={!refineInput.trim() || refineLoading}
              >
                {refineLoading ? (
                  <>
                    <span className="loading-spinner-small"></span>
                    完善中…
                  </>
                ) : (
                  '发送'
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 空状态 */}
      {!draft && !loading && (
        <div className="empty-state card">
          <div className="empty-illustration">
            <span className="empty-icon">📝</span>
          </div>
          <h3>开始生成您的文献综述</h3>
          <p>输入研究主题和时间范围，AI 将自动分析相关文献并生成结构化的综述草稿</p>
          <div className="features-grid">
            <div className="feature-item">
              <span className="feature-icon">🔍</span>
              <span className="feature-text">智能文献检索</span>
            </div>
            <div className="feature-item">
              <span className="feature-icon">🧠</span>
              <span className="feature-text">AI 内容生成</span>
            </div>
            <div className="feature-item">
              <span className="feature-icon">📊</span>
              <span className="feature-text">结构化章节</span>
            </div>
            <div className="feature-item">
              <span className="feature-icon">📑</span>
              <span className="feature-text">自动引用</span>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
