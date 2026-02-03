import React, { useEffect, useState } from 'react'
import BaseChart from '../components/BaseChart'
import type { EChartsOption } from 'echarts'
import { getDashboardStats, type DashboardStats } from '../api'
import ChatSidebar from '../components/ChatSidebar'
import './Dashboard.css'

const emptyStats: DashboardStats = {
  yearlyCounts: [],
  topKeywords: [],
  attitudeDistribution: [],
  researchPathDistribution: [],
  clusters: [],
  topicDistribution: [],
  cooccurrence: { nodes: [], links: [] },
  trendSeries: { years: [], series: [] },
  attitudeEvolution: { years: [], series: [] },
}

const years = Array.from({ length: 2025 - 2000 + 1 }, (_, i) => 2000 + i)

// 配色方案
const chartColors = {
  primary: '#f97316',
  secondary: '#8b5cf6',
  tertiary: '#06b6d4',
  quaternary: '#10b981',
  gradient: ['#f97316', '#fb923c', '#fdba74'],
  pie: ['#f97316', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ec4899'],
}

export function DashboardPage() {
  const [topic, setTopic] = useState('数字贸易规则')
  const [startYear, setStartYear] = useState<number | undefined>(2015)
  const [endYear, setEndYear] = useState<number | undefined>(2025)
  const [stats, setStats] = useState<DashboardStats>(emptyStats)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function loadStats() {
    setLoading(true)
    setError(null)
    getDashboardStats({ topic: topic || undefined, startYear, endYear })
      .then(setStats)
      .catch((err) => { setError(err?.message); setStats(emptyStats) })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadStats()
  }, [])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      loadStats()
    }
  }

  const useStats = stats ?? emptyStats

  const lineOption: EChartsOption = {
    tooltip: { 
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#334155' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { 
      type: 'category', 
      data: useStats.yearlyCounts.map((y) => String(y.year)),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b' },
    },
    yAxis: { 
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#64748b' },
    },
    series: [{
      type: 'line',
      data: useStats.yearlyCounts.map((y) => y.count),
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 3, color: chartColors.primary },
      itemStyle: { color: chartColors.primary, borderWidth: 2, borderColor: '#fff' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(249, 115, 22, 0.3)' },
            { offset: 1, color: 'rgba(249, 115, 22, 0.05)' },
          ],
        },
      },
    }],
  }

  const kwMaxLen = 8
  const barOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e2e8f0',
      textStyle: { color: '#334155' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const idx = p?.dataIndex
        if (idx != null && useStats.topKeywords[idx]) {
          return useStats.topKeywords[idx].name + ': ' + useStats.topKeywords[idx].value
        }
        return p?.name + ': ' + p?.value ?? ''
      },
    },
    grid: { left: '3%', right: '4%', bottom: '12%', containLabel: true },
    xAxis: { 
      type: 'category', 
      data: useStats.topKeywords.map((k) => k.name.length > kwMaxLen ? k.name.slice(0, kwMaxLen) + '…' : k.name),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', rotate: 30, fontSize: 11 },
    },
    yAxis: { 
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#64748b' },
    },
    series: [{
      type: 'bar',
      data: useStats.topKeywords.map((k) => k.value),
      itemStyle: {
        borderRadius: [6, 6, 0, 0],
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: chartColors.primary },
            { offset: 1, color: chartColors.gradient[2] },
          ],
        },
      },
      barWidth: '60%',
    }],
  }

  const pieOption: EChartsOption = {
    tooltip: { 
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e2e8f0',
      textStyle: { color: '#334155' },
    },
    legend: {
      orient: 'vertical',
      right: '5%',
      top: 'center',
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['40%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 8,
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: { show: false },
      emphasis: {
        label: { show: true, fontSize: 14, fontWeight: 'bold' },
        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.2)' },
      },
      data: useStats.attitudeDistribution.map((item, index) => ({
        ...item,
        itemStyle: { color: chartColors.pie[index % chartColors.pie.length] },
      })),
    }],
  }

  const attitudeEvolutionOption: EChartsOption = useStats.attitudeEvolution?.years?.length
    ? {
        tooltip: { 
          trigger: 'axis',
          backgroundColor: 'rgba(255, 255, 255, 0.95)',
          borderColor: '#e2e8f0',
          textStyle: { color: '#334155' },
        },
        legend: { 
          data: useStats.attitudeEvolution.series?.map((s) => s.name) || [],
          bottom: 0,
          textStyle: { color: '#64748b' },
        },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: { 
          type: 'category', 
          data: useStats.attitudeEvolution.years.map(String),
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          axisLabel: { color: '#64748b' },
        },
        yAxis: { 
          type: 'value',
          axisLine: { show: false },
          splitLine: { lineStyle: { color: '#f1f5f9' } },
          axisLabel: { color: '#64748b' },
        },
        series: (useStats.attitudeEvolution.series || []).map((s, i) => ({
          name: s.name,
          type: 'bar',
          stack: 'total',
          data: s.data,
          itemStyle: { 
            color: chartColors.pie[i % chartColors.pie.length],
            borderRadius: i === (useStats.attitudeEvolution.series || []).length - 1 ? [4, 4, 0, 0] : 0,
          },
        })),
      }
    : { series: [] }

  const cooccurrenceOption: EChartsOption =
    useStats.cooccurrence?.nodes?.length && useStats.cooccurrence?.links?.length
      ? {
          tooltip: {
            backgroundColor: 'rgba(255, 255, 255, 0.95)',
            borderColor: '#e2e8f0',
            textStyle: { color: '#334155' },
          },
          series: [
            {
              type: 'graph',
              layout: 'force',
              data: useStats.cooccurrence.nodes.map((n) => ({
                id: n.id,
                name: n.name,
                value: n.value,
                symbolSize: Math.min(40, Math.max(16, (n.value || 1) * 4)),
                itemStyle: { color: chartColors.primary },
              })),
              links: useStats.cooccurrence.links.map((l) => ({
                source: l.source,
                target: l.target,
                value: l.value,
                lineStyle: { color: '#cbd5e1', width: Math.min(3, l.value * 0.5) },
              })),
              roam: true,
              label: { 
                show: true, 
                position: 'right',
                color: '#334155',
                fontSize: 11,
              },
              force: { repulsion: 250, edgeLength: 100 },
              emphasis: {
                focus: 'adjacency',
                lineStyle: { width: 4 },
              },
            },
          ],
        }
      : { series: [] }

  const clusters = useStats.clusters ?? []
  const clusterChartOption: EChartsOption = clusters.length
    ? {
        tooltip: {
          trigger: 'axis',
          backgroundColor: 'rgba(255, 255, 255, 0.95)',
          borderColor: '#e2e8f0',
          textStyle: { color: '#334155' },
        },
        grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
        xAxis: { 
          type: 'category', 
          data: clusters.map((c) => (c.topic_name || `主题${c.cluster_id}`).slice(0, 10)),
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          axisLabel: { rotate: 25, color: '#64748b', fontSize: 11 },
        },
        yAxis: { 
          type: 'value',
          axisLine: { show: false },
          splitLine: { lineStyle: { color: '#f1f5f9' } },
          axisLabel: { color: '#64748b' },
        },
        series: [{
          type: 'bar',
          data: clusters.map((c, i) => ({
            value: c.count,
            itemStyle: { 
              color: chartColors.pie[i % chartColors.pie.length],
              borderRadius: [6, 6, 0, 0],
            },
          })),
          barWidth: '60%',
        }],
      }
    : { series: [] }

  return (
    <div className="dashboard-page">
      {/* 页面头部 */}
      <header className="page-header">
        <div className="page-title-section">
          <h1 className="page-title">分析仪表盘</h1>
          <p className="page-subtitle">可视化研究趋势与数据洞察</p>
        </div>
      </header>

      {/* 筛选表单 */}
      <div className="dashboard-form card">
        <div className="form-group">
          <label className="form-label">研究主题</label>
          <input
            className="form-input"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入研究主题，如：数字贸易规则"
          />
        </div>
        <div className="form-group">
          <label className="form-label">时间范围</label>
          <div className="year-range">
            <select value={startYear ?? ''} onChange={(e) => setStartYear(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">起始年份</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="range-separator">—</span>
            <select value={endYear ?? ''} onChange={(e) => setEndYear(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">结束年份</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>
        <button type="button" className="btn primary" onClick={loadStats} disabled={loading}>
          {loading ? (
            <>
              <span className="loading-spinner-small"></span>
              分析中...
            </>
          ) : (
            <>📊 刷新分析</>
          )}
        </button>
      </div>

      {loading && (
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
          <span>正在分析数据...</span>
        </div>
      )}
      {error && <div className="error">{error}</div>}

      {/* 主体内容 */}
      <div className="dashboard-body">
        {/* 图表区域 */}
        <section className="dashboard-charts">
          {/* 年度发文量 - 大卡片 */}
          <div className="chart-card chart-full">
            <div className="chart-header">
              <div className="chart-title-section">
                <span className="chart-icon">📈</span>
                <h3 className="chart-title">年度发文量趋势</h3>
              </div>
              <span className="chart-badge">时间序列</span>
            </div>
            <BaseChart option={lineOption} height={280} />
          </div>

          {/* 主题聚类 - 大卡片 */}
          {clusters.length > 0 && (
            <div className="chart-card chart-full">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-icon">🎯</span>
                  <h3 className="chart-title">主题聚类分布</h3>
                </div>
                <span className="chart-badge">聚类分析</span>
              </div>
              <BaseChart option={clusterChartOption} height={260} />
            </div>
          )}

          {/* 双列图表 */}
          <div className="chart-row">
            <div className="chart-card">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-icon">🏷️</span>
                  <h3 className="chart-title">关键词 Top 10</h3>
                </div>
              </div>
              <BaseChart option={barOption} height={240} />
            </div>
            <div className="chart-card">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-icon">🎭</span>
                  <h3 className="chart-title">研究态度分布</h3>
                </div>
              </div>
              <BaseChart option={pieOption} height={240} />
            </div>
          </div>

          {/* 态度演化 - 大卡片 */}
          {useStats.attitudeEvolution?.years?.length ? (
            <div className="chart-card chart-full">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-icon">📊</span>
                  <h3 className="chart-title">研究态度演化</h3>
                </div>
                <span className="chart-badge">堆叠图</span>
              </div>
              <BaseChart option={attitudeEvolutionOption} height={280} />
            </div>
          ) : null}

          {/* 关键词共现网络 - 大卡片 */}
          {useStats.cooccurrence?.nodes?.length ? (
            <div className="chart-card chart-full">
              <div className="chart-header">
                <div className="chart-title-section">
                  <span className="chart-icon">🕸️</span>
                  <h3 className="chart-title">关键词共现网络</h3>
                </div>
                <span className="chart-badge">网络图</span>
              </div>
              <BaseChart option={cooccurrenceOption} height={360} />
            </div>
          ) : null}
        </section>

        {/* AI 助理：标题与「新聊天」在 ChatSidebar 内，本区域限定高度使聊天区可滚动 */}
        <section className="dashboard-assistant">
          <ChatSidebar topic={topic} startYear={startYear} endYear={endYear} />
        </section>
      </div>
    </div>
  )
}
