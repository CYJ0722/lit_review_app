import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import { SearchPage } from './pages/Search'
import { DashboardPage } from './pages/Dashboard'
import { ReviewPage } from './pages/Review'
import './styles.css'

function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/search" replace />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/review" element={<ReviewPage />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')!).render(<App />)
