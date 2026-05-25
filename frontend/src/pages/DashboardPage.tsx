import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Camera, Wifi, WifiOff, Users, UserX } from 'lucide-react'
import { getCameras, addCamera } from '../lib/api'
import LiveFeed from '../components/LiveFeed'

export default function DashboardPage() {
  const [cameras, setCameras] = useState<any[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const navigate = useNavigate()

  const refresh = useCallback(() => {
    getCameras().then(setCameras).catch(console.error)
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleAdd = async () => {
    if (!newName.trim() || !newUrl.trim()) return
    setAdding(true)
    try {
      await addCamera(newName, newUrl)
      setNewName('')
      setNewUrl('')
      setShowAdd(false)
      refresh()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setAdding(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">Dashboard</h2>
          <p className="text-gray-400 text-sm mt-1">{cameras.length} camera{cameras.length !== 1 ? 's' : ''} configured</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 bg-cyan-500 hover:bg-cyan-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="w-4 h-4" /> Add Camera
        </button>
      </div>

      {/* Add Camera Dialog */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md">
            <h3 className="text-lg font-bold text-white mb-4">Add Camera</h3>
            <div className="space-y-3">
              <input
                type="text"
                placeholder="Camera name (e.g., Reception Cam)"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-cyan-500"
              />
              <input
                type="text"
                placeholder="RTSP URL (e.g., rtsp://192.168.1.100:554/stream)"
                value={newUrl}
                onChange={e => setNewUrl(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div className="flex gap-3 mt-5">
              <button
                onClick={() => setShowAdd(false)}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 py-2 rounded-lg text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleAdd}
                disabled={adding}
                className="flex-1 bg-cyan-500 hover:bg-cyan-600 text-white py-2 rounded-lg text-sm disabled:opacity-50"
              >
                {adding ? 'Adding...' : 'Add Camera'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Camera Grid */}
      {cameras.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-500">
          <Camera className="w-16 h-16 mb-4 opacity-30" />
          <p className="text-lg">No cameras added yet</p>
          <p className="text-sm mt-1">Click "Add Camera" to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {cameras.map(cam => (
            <div
              key={cam.id}
              onClick={() => navigate(`/camera/${cam.id}`)}
              className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden cursor-pointer hover:border-cyan-500/40 transition-colors group"
            >
              {/* Live preview */}
              <div className="aspect-video bg-gray-950 relative">
                <LiveFeed cameraId={cam.id} className="w-full h-full object-cover" />
                {/* Status indicator */}
                <div className="absolute top-2 right-2">
                  {cam.pipeline?.connected ? (
                    <span className="flex items-center gap-1 bg-green-500/20 text-green-400 text-xs px-2 py-1 rounded-full border border-green-500/30">
                      <Wifi className="w-3 h-3" /> Live
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 bg-red-500/20 text-red-400 text-xs px-2 py-1 rounded-full border border-red-500/30">
                      <WifiOff className="w-3 h-3" /> Offline
                    </span>
                  )}
                </div>
              </div>
              {/* Info */}
              <div className="p-3">
                <h3 className="text-white font-medium text-sm">{cam.name}</h3>
                <p className="text-gray-500 text-xs mt-1 truncate">{cam.rtsp_url}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
