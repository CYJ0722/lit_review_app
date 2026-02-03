import React from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import './AppLayout.css'

const navItems = [
  { path: '/search', icon: '🔍', label: '文献检索' },
  { path: '/dashboard', icon: '📊', label: '分析仪表盘' },
  { path: '/review', icon: '📝', label: '综述编辑器' },
]

export default function AppLayout({ children }: { children?: React.ReactNode }) {
  const location = useLocation()
  
  return (
    <div className="app-layout">
      {/* 左侧导航栏 */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="logo">
            <span className="logo-icon">📚</span>
            <span className="logo-text">文献助手</span>
          </div>
        </div>
        
        <nav className="sidebar-nav">
          <div className="nav-section">
            <span className="nav-section-title">功能菜单</span>
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              >
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-label">{item.label}</span>
                {location.pathname === item.path && <span className="nav-indicator" />}
              </NavLink>
            ))}
          </div>
        </nav>
        
        <div className="sidebar-footer">
          <div className="sidebar-info">
            <span className="info-icon">💡</span>
            <span className="info-text">智能文献分析平台</span>
          </div>
        </div>
      </aside>
      
      {/* 主内容区 */}
      <main className="main-content">
        <div className="content-wrapper">
          {children}
        </div>
      </main>
    </div>
  )
}
