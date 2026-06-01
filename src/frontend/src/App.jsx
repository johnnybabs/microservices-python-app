import React, { useState } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Upload from './pages/Upload'
import Download from './pages/Download'
import Dashboard from './pages/Dashboard'
import Architecture from './pages/Architecture'

export default function App() {
  const [token, setToken] = useState(null)

  const nav = 'px-4 py-2 rounded hover:bg-purple-800 transition-colors'
  const active = 'bg-purple-700'

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-indigo-950 border-b border-indigo-800 px-6 py-3 flex items-center justify-between">
        <span className="text-xl font-bold text-purple-400">🎙 VidCast</span>
        {token && (
          <nav className="flex gap-2 text-sm">
            <NavLink to="/upload" className={({ isActive }) => `${nav} ${isActive ? active : ''}`}>Upload</NavLink>
            <NavLink to="/download" className={({ isActive }) => `${nav} ${isActive ? active : ''}`}>Download</NavLink>
            <NavLink to="/dashboard" className={({ isActive }) => `${nav} ${isActive ? active : ''}`}>Dashboard</NavLink>
            <NavLink to="/architecture" className={({ isActive }) => `${nav} ${isActive ? active : ''}`}>Architecture</NavLink>
            <button onClick={() => setToken(null)} className={`${nav} text-red-400`}>Logout</button>
          </nav>
        )}
      </header>

      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={token ? <Navigate to="/upload" /> : <Login onLogin={setToken} />} />
          <Route path="/upload" element={token ? <Upload token={token} /> : <Navigate to="/" />} />
          <Route path="/download" element={token ? <Download token={token} /> : <Navigate to="/" />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/architecture" element={<Architecture />} />
        </Routes>
      </main>

      <footer className="text-center text-xs text-gray-600 py-3">
        VidCast — built on AWS EKS · React + Flask + RabbitMQ + MongoDB
      </footer>
    </div>
  )
}
