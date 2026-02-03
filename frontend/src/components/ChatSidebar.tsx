import React, { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { askAnalysisAssistant } from '../api'
import './ChatSidebar.css'

type Msg = { id: string; role: 'user' | 'assistant' | 'system'; content: string; meta?: { referencedPaperIds?: string[] } }

/** 简单把 ** 转为加粗，避免多余字符感 */
function renderAssistantContent(text: string) {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return parts.map((part, i) => i % 2 === 1 ? <strong key={i}>{part}</strong> : part)
}

const CHAT_STORAGE_KEY = 'lit_dashboard_chat'

export interface ChatSidebarProps {
  topic?: string
  startYear?: number
  endYear?: number
  }

export default function ChatSidebar({ topic = '', startYear, endYear }: ChatSidebarProps) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (loaded) return
    try {
      const raw = sessionStorage.getItem(CHAT_STORAGE_KEY)
      if (raw) {
        const arr = JSON.parse(raw)
        if (Array.isArray(arr) && arr.length) setMsgs(arr)
      }
    } catch {}
    setLoaded(true)
  }, [loaded])

  useEffect(() => {
    if (!loaded || msgs.length === 0) return
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(msgs))
    } catch {}
  }, [loaded, msgs])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs])

  async function send() {
    if (!input.trim() || isLoading) return
    const content = input.trim()
    setMsgs((s) => [...s, { id: Date.now().toString(), role: 'user', content }])
    setInput('')
    setIsLoading(true)
    
    const loadingId = (Date.now() + 1).toString()
    setMsgs((s) => [...s, { id: loadingId, role: 'system', content: '正在思考...' }])
    
    try {
      const res = await askAnalysisAssistant({ question: content, topic, startYear, endYear })
      setMsgs((s) => s.filter((m) => m.id !== loadingId))
      const answerText = (res.answer || '').trim()
      const displayAnswer = answerText === '' || answerText === '暂无回复。'
        ? 'AI 暂无文字回复，请重试或换一种问法。'
        : answerText
      setMsgs((s) => [...s, {
        id: (Date.now() + 2).toString(),
        role: 'assistant',
        content: displayAnswer,
        meta: { referencedPaperIds: res.referencedPaperIds },
      }])
    } catch (err: any) {
      setMsgs((s) => s.filter((m) => m.id !== loadingId))
      const msg = err?.name === 'AbortError' ? '请求超时，请稍后重试。' : (err?.message || String(err))
      setMsgs((s) => [...s, {
        id: (Date.now() + 3).toString(),
        role: 'assistant',
        content: '抱歉，回复失败：' + msg,
      }])
    } finally {
      setIsLoading(false)
    }
  }

  function handleNewChat() {
    setMsgs([])
    setInput('')
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY)
    } catch {}
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="chat-sidebar">
      <div className="chat-sidebar-title-row">
        <span className="assistant-icon">🤖</span>
        <span className="assistant-title">AI 分析助理</span>
        <button type="button" className="btn-new-chat" onClick={handleNewChat}>
          新聊天
        </button>
      </div>
      {/* 消息列表：固定高度、内部滚动 */}
      <div className="chat-messages" ref={listRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            <span className="empty-icon">💬</span>
            <p>向 AI 助理提问</p>
            <div className="suggestion-chips">
              <button 
                className="suggestion-chip"
                onClick={() => setInput('这个研究领域的主要趋势是什么？')}
              >
                主要研究趋势
              </button>
              <button 
                className="suggestion-chip"
                onClick={() => setInput('有哪些研究热点？')}
              >
                研究热点
              </button>
              <button 
                className="suggestion-chip"
                onClick={() => setInput('关键词分布说明了什么？')}
              >
                关键词分析
              </button>
            </div>
          </div>
        )}
        
        {msgs.map((m) => (
          <div key={m.id} className={`chat-message ${m.role}`}>
            {m.role !== 'system' && (
              <div className="message-avatar">
                {m.role === 'user' ? '👤' : '🤖'}
              </div>
            )}
            <div className="message-content">
              {m.role === 'system' ? (
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              ) : (
                <>
                  <div className="message-text">
                    {m.role === 'assistant' ? renderAssistantContent(m.content) : m.content}
                  </div>
                  {m.meta?.referencedPaperIds?.length ? (
                    <div className="message-refs">
                      <span className="refs-label">📎 引用文献：</span>
                      {m.meta.referencedPaperIds.map((id) => (
                        <Link 
                          key={id} 
                          to={`/search?paperId=${encodeURIComponent(id)}`} 
                          className="ref-link"
                        >
                          [{id.slice(0, 6)}...]
                        </Link>
                      ))}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
      
      {/* 输入区域 */}
      <div className="chat-input-area">
        <div className="input-wrapper">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="输入问题，按 Enter 发送..."
            disabled={isLoading}
          />
          <button 
            className="send-btn" 
            onClick={send} 
            disabled={!input.trim() || isLoading}
          >
            {isLoading ? (
              <span className="sending-spinner"></span>
            ) : (
              <span>➤</span>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
