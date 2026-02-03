/**
 * 前端 API：直接请求本机后端（Vite 代理 /api -> http://localhost:8000）
 */
export interface PaperStructured {
  background?: string
  research_question?: string
  methods?: string
  conclusions?: string
  contributions?: string
  limitations?: string
}

export interface PaperAbstractMeta {
  keywords?: string
  clc?: string
  docCode?: string
  articleId?: string
}

export interface Paper {
  id: string
  title: string
  authors: string[]
  year: number
  journal: string
  keywords: string[]
  abstract: string
  topicId?: string
  structured?: PaperStructured
  /** 摘要中拆出的元数据（关键词、中图分类号等），用于详情分框展示 */
  abstractMeta?: PaperAbstractMeta | null
}

export interface DashboardStats {
  yearlyCounts: { year: number; count: number }[]
  topKeywords: { name: string; value: number }[]
  attitudeDistribution: { name: string; value: number }[]
  researchPathDistribution?: { name: string; value: number }[]
  clusters?: { cluster_id: number; topic_name: string; count: number }[]
  topicDistribution?: { topic_id: string; count: number }[]
  cooccurrence?: { nodes: { id: string; name: string; value: number }[]; links: { source: string; target: string; value: number }[] }
  trendSeries?: { years: number[]; series: { name: string; data: number[] }[] }
  attitudeEvolution?: { years: number[]; series: { name: string; data: number[]; stack?: string }[] }
}

const API = '' // 同源，由 Vite proxy 转发到后端

export interface SearchResponse {
  results: Paper[]
  total: number
  topicDistribution?: { topic_id: string; count: number }[]
  yearDistribution?: { year: number; count: number }[]
}

export async function searchPapers(params: {
  topic?: string
  startYear?: number
  endYear?: number
}): Promise<SearchResponse> {
  const q = new URLSearchParams()
  if (params.topic != null) q.set('topic', params.topic)
  if (params.startYear != null) q.set('startYear', String(params.startYear))
  if (params.endYear != null) q.set('endYear', String(params.endYear))
  const res = await fetch(`${API}/api/search?${q}`)
  if (!res.ok) throw new Error(await res.text())
  const data: SearchResponse = await res.json()
  return {
    results: Array.isArray(data.results) ? data.results : [],
    total: data.total ?? 0,
    topicDistribution: data.topicDistribution ?? [],
    yearDistribution: data.yearDistribution ?? [],
  }
}

export async function getDashboardStats(params: {
  topic?: string
  startYear?: number
  endYear?: number
}): Promise<DashboardStats> {
  const q = new URLSearchParams()
  if (params.topic != null) q.set('topic', params.topic ?? '')
  if (params.startYear != null) q.set('startYear', String(params.startYear))
  if (params.endYear != null) q.set('endYear', String(params.endYear))
  const res = await fetch(`${API}/api/dashboard/stats?${q}`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return {
    yearlyCounts: data.yearlyCounts ?? [],
    topKeywords: data.topKeywords ?? [],
    attitudeDistribution: data.attitudeDistribution ?? [],
    researchPathDistribution: data.researchPathDistribution ?? [],
    clusters: data.clusters ?? [],
    topicDistribution: data.topicDistribution ?? [],
    cooccurrence: data.cooccurrence ?? { nodes: [], links: [] },
    trendSeries: data.trendSeries ?? { years: [], series: [] },
    attitudeEvolution: data.attitudeEvolution ?? { years: [], series: [] },
  }
}

export async function askAnalysisAssistant(params: {
  question: string
  topic?: string
  startYear?: number
  endYear?: number
}): Promise<{ answer: string; referencedPaperIds: string[] }> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 125000) // 125s，略大于后端 120s
  try {
    const res = await fetch(`${API}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  } finally {
    clearTimeout(timeout)
  }
}

export async function generateReviewFast(params: {
  topic: string
  startYear?: number
  endYear?: number
}): Promise<{ draft: string; paperIds: string[] }> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 180000) // 3 分钟
  try {
    const res = await fetch(`${API}/api/review/fast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  } finally {
    clearTimeout(timeout)
  }
}

export async function exportReview(
  draft: string,
  format: 'txt' | 'latex'
): Promise<{ content: string; filename: string }> {
  const res = await fetch(`${API}/api/review/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft, format }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function refineReview(params: {
  draft: string
  question: string
  topic?: string
  paperIds?: string[]
}): Promise<{ draft: string }> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 130000) // 约 2 分钟
  try {
    const res = await fetch(`${API}/api/review/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        draft: params.draft,
        question: params.question,
        topic: params.topic,
        paperIds: params.paperIds,
      }),
      signal: controller.signal,
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  } finally {
    clearTimeout(timeout)
  }
}

export interface PaperBrief {
  id: string
  title: string
  authors: string[]
  year: number | string
  journal: string
}

export async function getPapersByIds(ids: string[]): Promise<PaperBrief[]> {
  if (!ids.length) return []
  const res = await fetch(`${API}/api/papers?ids=${encodeURIComponent(ids.join(','))}`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return data.papers ?? []
}
