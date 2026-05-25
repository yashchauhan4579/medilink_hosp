import { BrowserRouter, Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { LayoutDashboard, Camera, Bell, Settings, Plus, Activity } from 'lucide-react'
import DashboardPage from './pages/DashboardPage'
import CameraPage from './pages/CameraPage'
import AlertsPage from './pages/AlertsPage'
import SettingsPage from './pages/SettingsPage'
import { getActiveAlertCount } from './lib/api'
import { connectAlerts } from './lib/ws'

function Sidebar() {
  const [alertCount, setAlertCount] = useState(0)

  useEffect(() => {
    getActiveAlertCount().then(d => setAlertCount(d.count)).catch(() => {})
    const interval = setInterval(() => {
      getActiveAlertCount().then(d => setAlertCount(d.count)).catch(() => {})
    }, 10000)

    const unsub = connectAlerts(() => {
      setAlertCount(c => c + 1)
    })

    return () => { clearInterval(interval); unsub() }
  }, [])

  const links = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/alerts', icon: Bell, label: 'Alerts', badge: alertCount },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ]

  return (
    <aside className="w-60 bg-gray-900 border-r border-gray-800 flex flex-col min-h-screen">
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <Activity className="w-6 h-6 text-cyan-400" />
          <h1 className="text-lg font-bold text-white">Hospital Monitor</h1>
        </div>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {links.map(link => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`
            }
          >
            <link.icon className="w-4 h-4" />
            <span>{link.label}</span>
            {link.badge ? (
              <span className="ml-auto bg-red-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
                {link.badge}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-gray-800 text-xs text-gray-600">
        WiredLeap IRIS
      </div>
    </aside>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-gray-950">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/camera/:id" element={<CameraPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
