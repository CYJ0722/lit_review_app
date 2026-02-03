import { useEffect, useState, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { searchPapers, type Paper } from '../api'
import './Search.css'

const years = Array.from({ length: 2025 - 2000 + 1 }, (_, i) => 2000 + i)

/** 前端兜底：去掉摘要前导 ] 及元数据块，便于展示 */
function cleanAbstractForDisplay(text: string | undefined): string {
  if (!text || typeof text !== 'string') return ''
  let s = text.trim().replace(/^[\s\[\]［］]+/, '')
  s = s.replace(/\s*\[关键词\][^\[]*/gi, '').replace(/\s*\[中图分类号\][^\[]*/gi, '')
  s = s.replace(/\s*\[文献标识码\][^\[]*/gi, '').replace(/\s*\[文章编号\][^\[]*/gi, '')
  s = s.replace(/\s*\[DOI\][^\[]*/gi, '').replace(/\s+/g, ' ').trim()
  return s
}

function truncateAbstract(text: string | undefined, maxLen: number): string {
  const s = cleanAbstractForDisplay(text)
  return s.length > maxLen ? s.slice(0, maxLen) + '…' : s
}

const PREVIEW_CHARS = 120
function DetailBox({
  title,
  children,
  expanded,
  onToggle,
  previewLen = PREVIEW_CHARS,
}: {
  title: string
  children: string
  expanded: boolean
  onToggle: () => void
  previewLen?: number
}) {
  const text = (children || '').trim()
  const needFold = text.length > previewLen
  const show = needFold && !expanded ? text.slice(0, previewLen) : text
  return (
    <div className="detail-box">
      <h5 className="section-title">{title}</h5>
      <div className="detail-box-content">
        <p>{show}{needFold && !expanded ? '…' : ''}</p>
        {needFold && (
          <button type="button" className="detail-box-toggle" onClick={onToggle}>
            {expanded ? '收起' : '展开'}
          </button>
        )}
      </div>
    </div>
  )
}

type ViewMode = 'list' | 'byTopic'

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const paperIdFromUrl = searchParams.get('paperId') ? decodeURIComponent(searchParams.get('paperId')!) : null
  const selectedCardRef = useRef<HTMLDivElement>(null)
  const [topic, setTopic] = useState('')
  const [startYear, setStartYear] = useState<number | undefined>()
  const [endYear, setEndYear] = useState<number | undefined>()
  const [results, setResults] = useState<Paper[]>([])
  const [topicDistribution, setTopicDistribution] = useState<{ topic_id: string; count: number }[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<Paper | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [detailExpanded, setDetailExpanded] = useState<Record<string, boolean>>({})

  function toggleDetail(key: string) {
    setDetailExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  useEffect(() => {
    if (!paperIdFromUrl || !results.length) return
    const p = results.find((r) => r.id === paperIdFromUrl)
    if (p) {
      setSelected(p)
      setTimeout(() => selectedCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 150)
    }
  }, [results, paperIdFromUrl])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    searchPapers({ topic: '', startYear: undefined, endYear: undefined })
      .then((res) => {
        if (!cancelled) {
          setResults(res.results ?? [])
          setTopicDistribution(res.topicDistribution ?? [])
          setTotal(res.total ?? 0)
          setSelected(res.results?.[0] ?? null)
        }
      })
      .catch((err) => { if (!cancelled) setError(err?.message || '检索失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function runSearch() {
    setLoading(true)
    setError(null)
    try {
      const res = await searchPapers({ topic, startYear, endYear })
      setResults(res.results ?? [])
      setTopicDistribution(res.topicDistribution ?? [])
      setTotal(res.total ?? 0)
      setSelected(res.results?.[0] ?? null)
    } catch (err: any) {
      setError(err?.message || '检索失败')
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      runSearch()
    }
  }

  const resultsByTopic = useMemo(() => {
    const map = new Map<string, Paper[]>()
    const noTopic = ''
    for (const p of results) {
      const tid = p.topicId || noTopic
      if (!map.has(tid)) map.set(tid, [])
      map.get(tid)!.push(p)
    }
    const order = topicDistribution.map((t) => t.topic_id)
    const out: { topicId: string; label: string; papers: Paper[] }[] = []
    for (const tid of order) {
      const papers = map.get(tid)
      if (papers?.length) {
        out.push({ topicId: tid, label: tid || '未分类', papers })
        map.delete(tid)
      }
    }
    map.forEach((papers, tid) => {
      out.push({ topicId: tid, label: tid || '未分类', papers })
    })
    return out
  }, [results, topicDistribution])

  return (
    <div className="search-page">
      {/* 页面标题 */}
      <header className="page-header">
        <div className="page-title-section">
          <h1 className="page-title">文献检索</h1>
          <p className="page-subtitle">智能搜索与发现学术文献</p>
        </div>
        {results.length > 0 && (
          <div className="header-stats">
            <span className="stat-item">
              <span className="stat-number">{total}</span>
              <span className="stat-label">篇文献</span>
            </span>
          </div>
        )}
      </header>

      {/* 搜索表单 */}
      <div className="search-form-wrapper">
        <div className="search-form card">
          <div className="search-input-group">
            <input
              className="search-input"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入研究主题，如：数字贸易规则、人工智能..."
            />
          </div>
          <div className="search-filters">
            <select value={startYear ?? ''} onChange={(e) => setStartYear(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">起始年份</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="filter-separator">至</span>
            <select value={endYear ?? ''} onChange={(e) => setEndYear(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">结束年份</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <button className="btn primary search-btn" onClick={runSearch}>
            <span>检索文献</span>
          </button>
        </div>
      </div>

      {/* 视图切换 */}
      {results.length > 0 && (
        <div className="view-controls">
          <div className="view-mode-toggle">
            <button
              type="button"
              className={`toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
              onClick={() => setViewMode('list')}
            >
              <span className="toggle-icon">📋</span>
              列表视图
            </button>
            <button
              type="button"
              className={`toggle-btn ${viewMode === 'byTopic' ? 'active' : ''}`}
              onClick={() => setViewMode('byTopic')}
            >
              <span className="toggle-icon">📂</span>
              主题分组
            </button>
          </div>
        </div>
      )}

      {/* 主要内容区 */}
      <div className="search-content">
        {/* 左侧结果列表 */}
        <div className="results-col">
          {loading && (
            <div className="loading-state">
              <div className="loading-spinner"></div>
              <span>正在检索文献...</span>
            </div>
          )}
          {error && <div className="error">{error}</div>}
          {!loading && !error && results.length === 0 && (
            <div className="empty-state card">
              <span className="empty-icon">📖</span>
              <h3>开始您的文献探索</h3>
              <p>输入研究主题并点击检索，发现相关学术文献</p>
            </div>
          )}
          
          {/* 列表视图 */}
          {!loading && !error && results.length > 0 && viewMode === 'list' && (
            <div className="results-list">
              {results.map((p, index) => (
                <div
                  key={p.id}
                  ref={p.id === paperIdFromUrl ? selectedCardRef : undefined}
                  className={`paper-card card ${selected?.id === p.id ? 'selected' : ''}`}
                  onClick={() => setSelected(p)}
                  style={{ animationDelay: `${index * 0.05}s` }}
                >
                  <div className="paper-header">
                    <h3 className="paper-title">{p.title}</h3>
                    {p.topicId && <span className="paper-topic-badge">{p.topicId}</span>}
                  </div>
                  <div className="paper-meta">
                    <span className="meta-item">
                      <span className="meta-icon">📅</span>
                      {p.year}
                    </span>
                    <span className="meta-item">
                      <span className="meta-icon">📰</span>
                      {p.journal || '未知期刊'}
                    </span>
                  </div>
                  <p className="paper-abstract">{truncateAbstract(p.abstract, 150)}</p>
                </div>
              ))}
            </div>
          )}
          
          {/* 主题分组视图 */}
          {!loading && !error && results.length > 0 && viewMode === 'byTopic' && (
            <div className="results-by-topic">
              {resultsByTopic.map(({ topicId, label, papers }) => (
                <section key={topicId || 'none'} className="topic-group">
                  <div className="topic-group-header">
                    <span className="topic-icon">📁</span>
                    <h3 className="topic-group-title">{label}</h3>
                    <span className="topic-count">{papers.length} 篇</span>
                  </div>
                  <div className="topic-papers">
                    {papers.map((p) => (
                      <div
                        key={p.id}
                        ref={p.id === paperIdFromUrl ? selectedCardRef : undefined}
                        className={`paper-card-mini ${selected?.id === p.id ? 'selected' : ''}`}
                        onClick={() => setSelected(p)}
                      >
                        <h4 className="paper-title-mini">{p.title}</h4>
                        <div className="paper-meta-mini">
                          {p.year} · {p.journal || '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* 右侧预览面板 */}
        <aside className="preview-col">
          <div className="preview-panel card">
            <div className="preview-header">
              <span className="preview-icon">📄</span>
              <h4>文献详情</h4>
            </div>
            {selected ? (
              <div className="preview-content">
                <h3 className="preview-title">{selected.title}</h3>
                <div className="preview-meta">
                  {selected.year && (
                    <span className="preview-meta-item">
                      <span className="meta-icon">📅</span>
                      {selected.year}
                    </span>
                  )}
                  {selected.journal && (
                    <span className="preview-meta-item">
                      <span className="meta-icon">📰</span>
                      {selected.journal}
                    </span>
                  )}
                  {selected.topicId && (
                    <span className="preview-meta-item topic-badge">
                      {selected.topicId}
                    </span>
                  )}
                </div>
                <DetailBox
                  title="摘要"
                  expanded={!!detailExpanded['abstract']}
                  onToggle={() => toggleDetail('abstract')}
                  previewLen={180}
                >
                  {selected.abstract || ''}
                </DetailBox>
                {selected.abstractMeta && (selected.abstractMeta.keywords || selected.abstractMeta.clc || selected.abstractMeta.docCode || selected.abstractMeta.articleId) && (
                  <>
                    {selected.abstractMeta.keywords && (
                      <DetailBox title="关键词" expanded={!!detailExpanded['keywords']} onToggle={() => toggleDetail('keywords')} previewLen={80}>
                        {selected.abstractMeta.keywords}
                      </DetailBox>
                    )}
                    {selected.abstractMeta.clc && (
                      <DetailBox title="中图分类号" expanded={!!detailExpanded['clc']} onToggle={() => toggleDetail('clc')} previewLen={40}>
                        {selected.abstractMeta.clc}
                      </DetailBox>
                    )}
                    {selected.abstractMeta.docCode && (
                      <DetailBox title="文献标识码" expanded={!!detailExpanded['docCode']} onToggle={() => toggleDetail('docCode')} previewLen={20}>
                        {selected.abstractMeta.docCode}
                      </DetailBox>
                    )}
                    {selected.abstractMeta.articleId && (
                      <DetailBox title="文章编号" expanded={!!detailExpanded['articleId']} onToggle={() => toggleDetail('articleId')} previewLen={40}>
                        {selected.abstractMeta.articleId}
                      </DetailBox>
                    )}
                  </>
                )}
                {selected.structured && (selected.structured.background || selected.structured.research_question) && (
                  <div className="preview-section structured-section">
                    <h5 className="section-title">结构化信息</h5>
                    {selected.structured.background && (
                      <DetailBox title="研究背景" expanded={!!detailExpanded['bg']} onToggle={() => toggleDetail('bg')} previewLen={150}>
                        {selected.structured!.background}
                      </DetailBox>
                    )}
                    {selected.structured.research_question && (
                      <DetailBox title="研究问题" expanded={!!detailExpanded['rq']} onToggle={() => toggleDetail('rq')} previewLen={120}>
                        {selected.structured!.research_question}
                      </DetailBox>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="preview-empty">
                <span className="empty-icon">👆</span>
                <p>点击左侧文献查看详情</p>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
