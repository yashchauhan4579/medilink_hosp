import { useEffect, useState, useCallback } from 'react'
import { Bell, Check, Eye, Image } from 'lucide-react'
import { getAlerts, acknowledgeAlert, resolveAlert, getAlertSnapshotUrl } from '../lib/api'
import { connectAlerts } from '../lib/ws'

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<any[]>([])
  const [filter, setFilter] = useState<string>('all')
  const [moduleFilter, setModuleFilter] = useState<string>('all')
  const [viewSnapshot, setViewSnapshot] = useState<string | null>(null)

  const refresh = useCallback(() => {
    const params: Record<string, string> = { limit: '100' }
    if (filter !== 'all') params.status = filter
    if (moduleFilter !== 'all') params.module = moduleFilter
    getAlerts(params).then(setAlerts).catch(console.error)
  }, [filter, moduleFilter])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    const unsub = connectAlerts(() => refresh())
    return () => { clearInterval(interval); unsub() }
  }, [refresh])

  const handleAck = async (id: number) => {
    await acknowledgeAlert(id)
    refresh()
  }

  const handleResolve = async (id: number) => {
    await resolveAlert(id)
    refresh()
  }

  const statusColor = (s: string) => {
    if (s === 'active') return 'text-red-400 bg-red-500/10 border-red-500/30'
    if (s === 'acknowledged') return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30'
    return 'text-green-400 bg-green-500/10 border-green-500/30'
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-white">Alerts</h2>
        <div className="flex gap-2">
          <select
            value={moduleFilter}
            onChange={e => setModuleFilter(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300"
          >
            <option value="all">All Modules</option>
            <option value="reception">Reception</option>
            <option value="crowd">Crowd</option>
          </select>
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300"
          >
            <option value="all">All Status</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
      </div>

      {/* Snapshot Modal */}
      {viewSnapshot && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center" onClick={() => setViewSnapshot(null)}>
          <img src={getAlertSnapshotUrl(viewSnapshot)} className="max-w-3xl max-h-[80vh] rounded-lg" alt="Alert snapshot" />
        </div>
      )}

      {alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Bell className="w-16 h-16 mb-4 opacity-30" />
          <p>No alerts found</p>
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map(alert => (
            <div
              key={alert.id}
              className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex items-center gap-4"
            >
              {/* Module badge */}
              <span className={`text-xs font-bold px-2 py-1 rounded border ${
                alert.module === 'reception'
                  ? 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30'
                  : 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30'
              }`}>
                {alert.module.toUpperCase()}
              </span>

              {/* Message */}
              <div className="flex-1 min-w-0">
                <p className="text-white text-sm">{alert.message}</p>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-gray-500 text-xs">{alert.camera_name}</span>
                  <span className="text-gray-600 text-xs">{new Date(alert.created_at + 'Z').toLocaleString()}</span>
                  {alert.head_count !== null && (
                    <span className="text-gray-500 text-xs">Heads: {alert.head_count}</span>
                  )}
                  {alert.whatsapp_status && alert.whatsapp_status !== 'pending' && (
                    <span className={`text-xs ${alert.whatsapp_status === 'sent' ? 'text-green-500' : 'text-red-500'}`}>
                      WA: {alert.whatsapp_status}
                    </span>
                  )}
                </div>
              </div>

              {/* Status */}
              <span className={`text-xs px-2 py-1 rounded border ${statusColor(alert.status)}`}>
                {alert.status}
              </span>

              {/* Actions */}
              <div className="flex gap-1">
                {alert.snapshot_path && (
                  <button
                    onClick={() => setViewSnapshot(alert.snapshot_path)}
                    className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded"
                    title="View snapshot"
                  >
                    <Image className="w-4 h-4" />
                  </button>
                )}
                {alert.status === 'active' && (
                  <button
                    onClick={() => handleAck(alert.id)}
                    className="p-1.5 text-yellow-400 hover:bg-yellow-500/10 rounded"
                    title="Acknowledge"
                  >
                    <Eye className="w-4 h-4" />
                  </button>
                )}
                {alert.status !== 'resolved' && (
                  <button
                    onClick={() => handleResolve(alert.id)}
                    className="p-1.5 text-green-400 hover:bg-green-500/10 rounded"
                    title="Resolve"
                  >
                    <Check className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
