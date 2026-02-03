import React, { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

type Props = { 
  option: EChartsOption
  title?: string
  height?: number
}

export default function BaseChart({ option, title, height = 240 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    
    // 初始化或获取已有实例
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
    }
    
    chartRef.current.setOption(option, true)

    // 响应式调整
    const handleResize = () => {
      chartRef.current?.resize()
    }
    
    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [option])

  // 组件卸载时销毁
  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <div className="base-chart">
      <div 
        ref={ref} 
        style={{ 
          width: '100%', 
          height: `${height}px`,
          minHeight: `${height}px`,
        }} 
      />
    </div>
  )
}
